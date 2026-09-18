// jsdom implements neither API, and the resizable panes (ResizeObserver) and the
// command palette (scrollIntoView) both call them during a normal render.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver
Element.prototype.scrollIntoView ??= function scrollIntoView() {}
