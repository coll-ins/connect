// Where Tab should go inside a dialog with `count` focusable elements while
// `current` has focus (-1: focus is outside). null = let the browser move it.
export function nextFocusIndex(count, current, shift) {
  if (count === 0) return -1;
  if (current === -1) return shift ? count - 1 : 0;
  if (!shift && current === count - 1) return 0;
  if (shift && current === 0) return count - 1;
  return null;
}
