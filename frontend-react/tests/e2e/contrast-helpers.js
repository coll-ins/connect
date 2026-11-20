// Measures WCAG contrast from computed styles. Backgrounds with alpha are composited over
// their ancestors, so tinted chips and alerts are measured as the user sees them.
export async function measure(page, selector, { part = 'text', nth = 0 } = {}) {
  return page.locator(selector).nth(nth).evaluate((el, which) => {
    const parse = (value) => {
      const m = value.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
    };
    const over = (top, under) => ({
      r: top.r * top.a + under.r * (1 - top.a),
      g: top.g * top.a + under.g * (1 - top.a),
      b: top.b * top.a + under.b * (1 - top.a),
      a: 1,
    });
    const backdrop = (node) => {
      const layers = [];
      for (let n = node; n; n = n.parentElement) {
        const c = parse(getComputedStyle(n).backgroundColor);
        if (c && c.a > 0) layers.push(c);
        if (c && c.a === 1) break;
      }
      let acc = layers.length && layers[layers.length - 1].a === 1 ? layers.pop() : { r: 15, g: 17, b: 20, a: 1 };
      while (layers.length) acc = over(layers.pop(), acc);
      return acc;
    };
    const lum = ({ r, g, b }) => {
      const f = (v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
    const style = getComputedStyle(el);
    const own = backdrop(el);
    if (which === 'text') return { ratio: ratio(over(parse(style.color), own), own), fg: style.color };
    if (which === 'border') {
      const under = backdrop(el.parentElement);
      return { ratio: ratio(over(parse(style.borderTopColor), under), under), fg: style.borderTopColor };
    }
    if (which === 'outline') {
      const under = backdrop(el.parentElement);
      return { ratio: ratio(over(parse(style.outlineColor), under), under), fg: style.outlineColor };
    }
    // 'fill': the element's own background against the surface behind it
    const under = backdrop(el.parentElement);
    return { ratio: ratio(own, under), fg: style.backgroundColor };
  }, part);
}
