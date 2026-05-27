import { describe, it, expect, vi, afterEach } from 'vitest'

/**
 * 回歸:getEventsUrl / getAudioUrl 必須用跟 axios 相同的 API base
 * (resolveApiBase → 未設 VITE_API_URL 時 fallback 成 hostname:8000),
 * 不能各自 fallback 成空字串。
 *
 * 舊 bug:兩者用 `import.meta.env.VITE_API_URL ?? ''`,VITE_API_URL 未設時
 * 變空字串 → 組出相對 URL → EventSource 打到前端 dev server → SSE 404、
 * 即時狀態更新整條失效(任務完成不會即時顯示)。
 */
describe('services API base', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('getEventsUrl 在 VITE_API_URL 未設時用後端絕對 URL(非相對路徑)', async () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', hostname: 'example.test' } })
    vi.resetModules()
    const { taskService } = await import('./services')
    expect(taskService.getEventsUrl('t1', 'tok')).toBe(
      'http://example.test:8000/tasks/t1/events?token=tok'
    )
  })

  it('getAudioUrl 同樣用後端絕對 URL', async () => {
    vi.stubGlobal('window', { location: { protocol: 'http:', hostname: 'example.test' } })
    vi.resetModules()
    const { transcriptionService } = await import('./services')
    expect(transcriptionService.getAudioUrl('t1', 'tok')).toMatch(
      /^http:\/\/example\.test:8000\//
    )
  })
})
