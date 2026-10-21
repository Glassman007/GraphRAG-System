"""Extract the CREATE/ALTER table declarations in PostgreSQL pg_dump SQL.

The dump also contains psql COPY data, functions and other statements. Only
anchored table DDL is submitted to PostgreSQL's grammar via pglast. SQL is never
sent to a database or executed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pglast import ast, enums, parse_sql
from pglast.stream import RawStream


_TABLE_DDL = re.compile(r"(?ms)^CREATE TABLE\s+.*?^\);|^ALTER TABLE(?: ONLY)?\s+.*?;")
_COPY_START = re.compile(r"^COPY\s+.+\s+FROM stdin;\s*$")


def _hide_copy_data(text: str) -> str:
    """Remove psql COPY streams while preserving line numbers for evidence."""
    hidden = []
    copying = False
    for line in text.splitlines(keepends=True):
        if not copying and _COPY_START.match(line.rstrip("\r\n")):
            copying = True
            hidden.append("\n")
        elif copying:
            if line.strip() == r"\.":
                copying = False
            hidden.append("\n")
        else:
            hidden.append(line)
    if copying:
        raise ValueError("SQL artifact has an unterminated COPY data section")
    return "".join(hidden)


@dataclass
class SqlColumn:
    name: str
    data_type: str
    not_null: bool = False
    primary_key: bool = False


@dataclass
class SqlConstraint:
    name: str | None
    kind: str
    columns: tuple[str, ...]
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    ddl: str = ""
    line: int = 0


@dataclass
class SqlTable:
    schema: str
    name: str
    columns: dict[str, SqlColumn] = field(default_factory=dict)
    constraints: list[SqlConstraint] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass
class SqlSchema:
    tables: dict[str, SqlTable] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def foreign_keys(self) -> list[tuple[str, SqlConstraint]]:
        return [(name, c) for name, table in self.tables.items()
                for c in table.constraints if c.kind == "FOREIGN_KEY"]


def _qualified(range_var: ast.RangeVar, default_schema: str = "public") -> str:
    return f"{range_var.schemaname or default_schema}.{range_var.relname}"


def _names(values) -> tuple[str, ...]:
    return tuple(value.sval for value in values or ())


def _constraint(node: ast.Constraint, table: SqlTable, ddl: str, line: int,
                *, inline_column: str | None = None) -> SqlConstraint | None:
    # The statement can span several source lines. Keep the offset within the
    # original DDL instead of linking every constraint to its CREATE TABLE.
    if node.conname:
        declaration = re.search(r"\bCONSTRAINT\s+" + re.escape(node.conname) + r"\b", ddl, re.IGNORECASE)
    else:
        keyword = r"PRIMARY\s+KEY" if node.contype == enums.ConstrType.CONSTR_PRIMARY else "REFERENCES"
        declaration = re.search(keyword, ddl, re.IGNORECASE)
    if declaration:
        line += ddl.count("\n", 0, declaration.start())
    if node.contype == enums.ConstrType.CONSTR_PRIMARY:
        return SqlConstraint(node.conname, "PRIMARY_KEY", _names(node.keys) or ((inline_column,) if inline_column else ()),
                             ddl=ddl, line=line)
    if node.contype == enums.ConstrType.CONSTR_FOREIGN:
        if node.pktable is None:
            raise ValueError(f"Foreign key on {table.qualified_name} has no target table")
        return SqlConstraint(node.conname, "FOREIGN_KEY", _names(node.fk_attrs) or ((inline_column,) if inline_column else ()),
                             _qualified(node.pktable, table.schema), _names(node.pk_attrs), ddl, line)
    return None


def extract_postgres_schema(content: bytes) -> SqlSchema:
    """Parse selected table DDL from one UTF-8 PostgreSQL dump artifact."""
    if not isinstance(content, bytes):
        raise TypeError("SQL schema extraction requires source-file bytes")
    text = _hide_copy_data(content.decode("utf-8-sig"))
    result = SqlSchema()
    deferred: list[tuple[str, ast.Constraint, str, int]] = []
    for match in _TABLE_DDL.finditer(text):
        ddl = match.group()
        line = text.count("\n", 0, match.start()) + 1
        parsed = parse_sql(ddl)
        if len(parsed) != 1:
            raise ValueError(f"Expected one table statement at line {line}")
        stmt = parsed[0].stmt
        if isinstance(stmt, ast.CreateStmt):
            name = _qualified(stmt.relation)
            if name in result.tables:
                raise ValueError(f"Duplicate CREATE TABLE for {name}")
            table = SqlTable(stmt.relation.schemaname or "public", stmt.relation.relname)
            result.tables[name] = table
            for item in stmt.tableElts or ():
                if isinstance(item, ast.ColumnDef):
                    table.columns[item.colname] = SqlColumn(item.colname, RawStream()(item.typeName),
                                                             item.is_not_null or any(c.contype == enums.ConstrType.CONSTR_NOTNULL for c in item.constraints or ()))
                    for constraint in item.constraints or ():
                        parsed_constraint = _constraint(constraint, table, ddl, line, inline_column=item.colname)
                        if parsed_constraint:
                            table.constraints.append(parsed_constraint)
                elif isinstance(item, ast.Constraint):
                    parsed_constraint = _constraint(item, table, ddl, line)
                    if parsed_constraint:
                        table.constraints.append(parsed_constraint)
                else:
                    result.warnings.append(f"UNSUPPORTED_CREATE_TABLE_ELEMENT:{name}:{type(item).__name__}")
        elif isinstance(stmt, ast.AlterTableStmt):
            name = _qualified(stmt.relation)
            for command in stmt.cmds or ():
                if command.subtype == enums.AlterTableType.AT_AddConstraint and isinstance(command.def_, ast.Constraint):
                    deferred.append((name, command.def_, ddl, line))
                else:
                    result.warnings.append(f"UNSUPPORTED_ALTER_TABLE_COMMAND:{name}:{command.subtype}")
        else:
            raise ValueError(f"Unexpected table DDL at line {line}: {type(stmt).__name__}")

    if not result.tables:
        raise ValueError("SQL artifact contains no CREATE TABLE declarations")
    for name, node, ddl, line in deferred:
        table = result.tables.get(name)
        if table is None:
            raise ValueError(f"ALTER TABLE references undeclared table {name}")
        parsed_constraint = _constraint(node, table, ddl, line)
        if parsed_constraint:
            table.constraints.append(parsed_constraint)
        else:
            result.warnings.append(f"UNSUPPORTED_TABLE_CONSTRAINT:{name}:{node.contype}")

    for name, table in result.tables.items():
        for constraint in table.constraints:
            if constraint.kind == "PRIMARY_KEY":
                for column in constraint.columns:
                    if column not in table.columns:
                        raise ValueError(f"Primary key {constraint.name} references undeclared column {name}.{column}")
                    table.columns[column].primary_key = True
                    table.columns[column].not_null = True
            elif constraint.kind == "FOREIGN_KEY":
                target = result.tables.get(constraint.referenced_table or "")
                if target is None:
                    raise ValueError(f"Foreign key {constraint.name} references undeclared table {constraint.referenced_table}")
                if not constraint.columns or len(constraint.columns) != len(constraint.referenced_columns):
                    raise ValueError(f"Foreign key {constraint.name} has mismatched column lists")
                if any(c not in table.columns for c in constraint.columns) or any(c not in target.columns for c in constraint.referenced_columns):
                    raise ValueError(f"Foreign key {constraint.name} references undeclared columns")
    return result
