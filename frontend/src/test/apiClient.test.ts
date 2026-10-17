import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiRequest, ApiError, makeIdempotencyKey, queryString } from '../api/client'
const config={baseUrl:'http://api.test',token:'secret-token',tenantId:'tenant-a'}
afterEach(()=>vi.restoreAllMocks())
describe('API client',()=>{
 it('includes auth and tenant headers',async()=>{const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({ok:true}),{status:200,headers:{'Content-Type':'application/json'}}));await apiRequest(config,'/api/v1/test');const init=fetchMock.mock.calls[0][1] as RequestInit;const headers=new Headers(init.headers);expect(headers.get('Authorization')).toBe('Bearer secret-token');expect(headers.get('X-Tenant-ID')).toBe('tenant-a');expect(headers.get('X-Request-ID')).toBeTruthy()})
 it('parses Phase 11 error schema',async()=>{vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({error:{code:'FORBIDDEN',message:'no',request_id:'req-1'}}),{status:403}));await expect(apiRequest(config,'/api/v1/test')).rejects.toMatchObject({status:403,code:'FORBIDDEN',requestId:'req-1'} satisfies Partial<ApiError>)})
 it('passes AbortSignal for cancellation',async()=>{const controller=new AbortController();const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:200}));await apiRequest(config,'/x',{signal:controller.signal});expect((fetchMock.mock.calls[0][1] as RequestInit).signal).toBe(controller.signal)})
 it('sends idempotency key only when requested',async()=>{const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:200}));await apiRequest(config,'/x',{method:'POST',body:{x:1},idempotencyKey:'idem-1'});expect(new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers).get('Idempotency-Key')).toBe('idem-1')})
 it('creates distinct idempotency keys',()=>expect(makeIdempotencyKey()).not.toBe(makeIdempotencyKey()))
 it('serializes bounded query params',()=>expect(queryString({limit:50,status:'READY',empty:'',none:null})).toBe('?limit=50&status=READY'))
})
