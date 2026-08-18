import { describe, expect, it, vi } from 'vitest'

import { bootstrapApp } from './bootstrap'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('bootstrapApp', () => {
  it('路由就绪后立即挂载外壳，不等待数据初始化完成', async () => {
    const init = deferred()
    const app = { mount: vi.fn() }
    const router = {
      isReady: vi.fn().mockResolvedValue(),
      currentRoute: {
        value: {
          path: '/batches/SceneA', params: { sceneId: 'SceneA' }, query: { branch_tag: 'engine-ue5' },
        },
      },
    }
    const store = { init: vi.fn().mockReturnValue(init.promise) }
    const logger = { error: vi.fn() }

    const boot = bootstrapApp({ app, router, store, logger })
    await vi.waitFor(() => expect(store.init).toHaveBeenCalledWith('SceneA', 'engine-ue5'))

    expect(app.mount).toHaveBeenCalledWith('#app')
    expect(logger.error).not.toHaveBeenCalled()

    init.resolve()
    await boot
  })

  it('烘培数据深链不使用场景参数初始化批次列表', async () => {
    const app = { mount: vi.fn() }
    const router = {
      isReady: vi.fn().mockResolvedValue(),
      currentRoute: {
        value: {
          path: '/map-build/Coral_WP', params: { sceneId: 'Coral_WP' }, query: { branch_tag: 'engine-ue5' },
        },
      },
    }
    const store = { init: vi.fn().mockResolvedValue() }
    const logger = { error: vi.fn() }

    await bootstrapApp({ app, router, store, logger })

    expect(store.init).toHaveBeenCalledWith('', 'engine-ue5')
    expect(app.mount).toHaveBeenCalledWith('#app')
  })

  it('初始化失败仍保留已挂载页面并记录错误', async () => {
    const app = { mount: vi.fn() }
    const router = {
      isReady: vi.fn().mockResolvedValue(),
      currentRoute: { value: { params: {} } },
    }
    const store = { init: vi.fn().mockRejectedValue(new Error('offline')) }
    const logger = { error: vi.fn() }

    await bootstrapApp({ app, router, store, logger })

    expect(app.mount).toHaveBeenCalledWith('#app')
    expect(logger.error).toHaveBeenCalledWith('应用初始化失败', expect.any(Error))
  })
})
