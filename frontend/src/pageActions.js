let pageRefresh = null

export function registerPageRefresh(handler) {
  pageRefresh = handler
  return () => {
    if (pageRefresh === handler) pageRefresh = null
  }
}

export async function runPageRefresh(options = {}) {
  const handler = pageRefresh
  if (!handler) return false
  await handler(options)
  return true
}
