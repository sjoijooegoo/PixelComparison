export async function bootstrapApp({ app, router, store, logger, mountTarget = '#app' }) {
  try {
    await router.isReady()
  } catch (error) {
    // 路由初始化异常也要挂载外壳，避免用户只看到空白页。
    logger.error('初始路由解析失败', error)
  }

  // 应用壳只初始化项目元信息和设置；批次目录、截图网格与烘培数据由
  // 各自路由页面加载，避免深链首屏先发出错误工作区的请求。
  const initialization = store.init()
  app.mount(mountTarget)
  try {
    await initialization
  } catch (error) {
    logger.error('应用初始化失败', error)
  }
}
