import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { defaultConfig, loadConfig, saveConfig } from '../api/client'
import { getSession } from '../api/system'
import type { ApiConfig, SessionResponse } from '../api/types'

interface AuthContextValue {
  config: ApiConfig
  session?: SessionResponse
  sessionLoading: boolean
  setConfig: (next: ApiConfig) => void
  hasPermission: (permission: string) => boolean
  authenticated: boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [config, updateConfig] = useState<ApiConfig>(() => typeof window === 'undefined' ? defaultConfig() : loadConfig())
  const queryClient = useQueryClient()
  const sessionQuery = useQuery({
    queryKey: ['session', config.baseUrl, config.token, config.tenantId],
    queryFn: ({ signal }) => getSession(config, signal),
    enabled: Boolean(config.token),
    retry: false,
  })
  const value = useMemo<AuthContextValue>(() => ({
    config,
    session: sessionQuery.data,
    sessionLoading: sessionQuery.isLoading,
    authenticated: Boolean(sessionQuery.data),
    setConfig(next) {
      saveConfig(next)
      updateConfig(next)
      queryClient.clear()
    },
    hasPermission(permission) {
      const permissions = new Set(sessionQuery.data?.permissions || [])
      return permissions.has('ADMIN') || permissions.has(permission)
    },
  }), [config, queryClient, sessionQuery.data, sessionQuery.isLoading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used under AuthProvider')
  return value
}
