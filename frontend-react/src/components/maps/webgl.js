export const webglOk = (() => {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
})();

// The 3D bus needs a real GPU: on software WebGL (no GPU, blocklisted driver)
// compiling its shaders blocks the page for ~10 s, so it keeps the 2D marker.
const SOFTWARE_GL = /swiftshader|llvmpipe|softpipe|software|basic render/i;

export const gpuWebglOk = (() => {
  try {
    const gl = document.createElement('canvas').getContext('webgl2')
      || document.createElement('canvas').getContext('webgl');
    if (!gl) return false;
    const info = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
    return !SOFTWARE_GL.test(String(renderer));
  } catch {
    return false;
  }
})();
