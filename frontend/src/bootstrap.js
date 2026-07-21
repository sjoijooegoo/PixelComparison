export async function bootstrapApp({ app, router, store, logger, mountTarget = '#app' }) {
  let routeSceneId = ''
  try {
    await router.isReady()
    routeSceneId = router.currentRoute.value.params.sceneId
  } catch (error) {
    // 路由初始化异常也要挂载外壳，避免用户只看到空白页。
    logger.error('初始路由解析失败', error)
  }

  // init() 会在首次 await 前同步固定深链场景和 loading 状态。随后立即挂载，
  // 页面展示骨架；批次/列表图继续在后台加载，失败后可在页面内重试。
  const initialization = store.init(routeSceneId)
  app.mount(mountTarget)
  try {
    await initialization
  } catch (error) {
    logger.error('应用初始化失败', error)
  }
}
