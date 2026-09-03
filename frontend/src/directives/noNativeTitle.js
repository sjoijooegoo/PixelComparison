const noNativeTitleState = Symbol('no-native-title-state')

export function clearNativeTitle(element) {
  if (element.matches?.('.arco-select-view[title]')) element.removeAttribute('title')
  for (const select of element.querySelectorAll?.('.arco-select-view[title]') || []) {
    select.removeAttribute('title')
  }
}

export const vNoNativeTitle = {
  mounted(element) {
    const clear = () => clearNativeTitle(element)
    const observer = typeof MutationObserver === 'undefined'
      ? null
      : new MutationObserver(clear)
    element[noNativeTitleState] = { clear, observer }
    element.addEventListener('mouseenter', clear)
    element.addEventListener('focusin', clear)
    observer?.observe(element, {
      attributes: true,
      attributeFilter: ['title'],
      subtree: true,
    })
    clear()
  },
  updated(element) {
    clearNativeTitle(element)
  },
  beforeUnmount(element) {
    const state = element[noNativeTitleState]
    if (!state) return
    element.removeEventListener('mouseenter', state.clear)
    element.removeEventListener('focusin', state.clear)
    state.observer?.disconnect()
    delete element[noNativeTitleState]
  },
}
