import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setAccessToken } from './api'

const fetchMock = vi.fn<typeof fetch>()
const json = (value: unknown,status = 200) => new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}})
beforeEach(() => {vi.stubGlobal('fetch',fetchMock);setAccessToken('')})
afterEach(() => {vi.unstubAllGlobals();fetchMock.mockReset();setAccessToken('')})
describe('same-origin API contract', () => {
  it('encodes filters and forwards cancellation without a model API call', async () => {
    fetchMock.mockResolvedValueOnce(json({items:[],total:0}))
    const controller = new AbortController()
    await api.list({search:'<test> & q',status:'pending',category:'',language:'kk',priority:'p1'},100,controller.signal)
    const [url,options] = fetchMock.mock.calls[0]
    expect(Object.fromEntries(new URL(String(url), 'http://localhost').searchParams)).toEqual({limit:'100',offset:'100',status:'pending',language:'kk',priority:'p1',search:'<test> & q'})
    expect(options?.signal).toBe(controller.signal)
    expect(new Headers(options?.headers).get('Authorization')).toBeNull()
  })
  it('sends access tokens only in Authorization headers, not URLs or request bodies', async () => {
    fetchMock.mockResolvedValueOnce(json({status:'ok'}));setAccessToken(' local-admin-test-token ')
    await api.health()
    const [url,options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/health');expect(options?.body).toBeUndefined()
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer local-admin-test-token')
  })
  it('uses an explicit idempotency key for ticket creation', async () => {
    fetchMock.mockResolvedValueOnce(json({id:'synthetic-test'}))
    await api.create({kind:'report',text:'Synthetic test question'},'synthetic-request-key')
    const [url,options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/tickets');expect(options?.method).toBe('POST')
    expect(new Headers(options?.headers).get('Idempotency-Key')).toBe('synthetic-request-key')
  })
  it('passes optimistic revision on review, never real-send endpoints', async () => {
    fetchMock.mockResolvedValueOnce(json({id:'synthetic-test'}))
    await api.review('synthetic/id',{status:'simulated_sent',draft_reply:'Synthetic response',expected_revision:4})
    const [url,options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/tickets/synthetic%2Fid/review')
    expect(JSON.parse(options?.body as string)).toEqual({status:'simulated_sent',draft_reply:'Synthetic response',expected_revision:4})
  })
  it('treats stale revisions as a recoverable conflict', async () => {
    fetchMock.mockResolvedValueOnce(json({detail:'stale'},409))
    await expect(api.review('synthetic',{expected_revision:2})).rejects.toMatchObject({status:409,message:expect.stringContaining('уже изменено')})
  })
  it('does not accept HTML proxy responses as application data', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>Bad proxy</html>',{status:200,headers:{'Content-Type':'text/html'}}))
    await expect(api.health()).rejects.toBeInstanceOf(ApiError)
  })
  it('provides actionable auth errors without exposing server text', async () => {
    fetchMock.mockResolvedValueOnce(json({detail:'sensitive implementation details'},401))
    await expect(api.health()).rejects.toMatchObject({status:401,message:expect.stringContaining('токен доступа')})
  })
  it('preserves aborts so stale navigation results can be discarded', async () => {
    fetchMock.mockRejectedValueOnce(new DOMException('Aborted','AbortError'))
    await expect(api.health()).rejects.toMatchObject({name:'AbortError'})
  })
})
