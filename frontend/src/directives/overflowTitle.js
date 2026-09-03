const overflowTitleState = Symbol('overflow-title-state')

export function isOverflowing(element) {
  return element.scrollWidth > element.clientWidth + 1
    || element.scrollHeight > element.clientHeight + 1
}

export function syncOverflowTitle(element, value) {
  const title = value === null || value === undefined ? '' : String(value)
  if (title && isOverflowing(element)) element.setAttribute('title', title)
  else element.removeAttribute('title')
}

export const vOverflowTitle = {
  mounted(element, binding) {
    const state = {
      value: binding.value,
      refresh: null,
    }
    state.refresh = () => syncOverflowTitle(element, state.value)
    element[overflowTitleState] = state
    element.addEventListener('mouseenter', state.refresh)
    state.refresh()
  },
  updated(element, binding) {
    const state = element[overflowTitleState]
    if (!state) return
    state.value = binding.value
    state.refresh()
  },
  beforeUnmount(element) {
    const state = element[overflowTitleState]
    if (!state) return
    element.removeEventListener('mouseenter', state.refresh)
    delete element[overflowTitleState]
  },
}
