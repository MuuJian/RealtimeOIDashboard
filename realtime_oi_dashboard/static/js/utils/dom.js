export function syncChildren(parent, nextChildren) {
  let current = parent.firstChild;
  for (const child of nextChildren) {
    if (child === current) {
      current = current.nextSibling;
      continue;
    }
    parent.insertBefore(child, current);
  }

  while (current) {
    const next = current.nextSibling;
    current.remove();
    current = next;
  }
}
