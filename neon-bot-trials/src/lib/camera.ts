/**
 * Smooth-follow camera with cinematic behavior. Positions are world-space;
 * zoom is world→screen scale. The renderer applies the transform.
 */
export class Camera {
  x = 0;
  y = 0;
  zoom = 1;

  private targetX = 0;
  private targetY = 0;
  private targetZoom = 1;
  private shake = 0;
  private shakePhase = 0;

  snapTo(x: number, y: number, zoom = this.targetZoom): void {
    this.x = this.targetX = x;
    this.y = this.targetY = y;
    this.zoom = this.targetZoom = zoom;
  }

  follow(x: number, y: number, zoom?: number): void {
    this.targetX = x;
    this.targetY = y;
    if (zoom !== undefined) this.targetZoom = zoom;
  }

  addShake(amount: number): void {
    this.shake = Math.min(14, this.shake + amount);
  }

  /**
   * @param dt seconds since last render frame
   * @param cinematic slower, floatier tracking with speed-reactive zoom
   * @param speed subject speed (px/s) for cinematic zoom-out
   */
  update(dt: number, cinematic = false, speed = 0): void {
    const stiffness = cinematic ? 2.2 : 5.5;
    const k = 1 - Math.exp(-stiffness * dt);
    if (cinematic) {
      const speedZoom = Math.max(0.72, 1 - speed / 2600);
      this.targetZoom = this.targetZoom * 0.98 + speedZoom * 0.02;
    }
    this.x += (this.targetX - this.x) * k;
    this.y += (this.targetY - this.y) * k;
    this.zoom += (this.targetZoom - this.zoom) * (1 - Math.exp(-3 * dt));
    this.shake *= Math.exp(-6 * dt);
    this.shakePhase += dt * 60;
  }

  /** Effective position including shake offset. */
  effective(): { x: number; y: number; zoom: number } {
    const sx = Math.sin(this.shakePhase * 1.3) * this.shake;
    const sy = Math.cos(this.shakePhase * 1.7) * this.shake * 0.7;
    return { x: this.x + sx, y: this.y + sy, zoom: this.zoom };
  }

  /**
   * Applies the camera transform on top of `base` (the canvas' DPR transform).
   * Resetting to identity instead would draw CSS-pixel coordinates in device
   * pixels — everything shrinks on hiDPI screens.
   */
  applyTo(ctx: CanvasRenderingContext2D, viewW: number, viewH: number, base?: DOMMatrix): void {
    const { x, y, zoom } = this.effective();
    if (base) ctx.setTransform(base);
    else ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.transform(zoom, 0, 0, zoom, viewW / 2 - x * zoom, viewH / 2 - y * zoom);
  }

  screenToWorld(sx: number, sy: number, viewW: number, viewH: number): { x: number; y: number } {
    const { x, y, zoom } = this.effective();
    return { x: (sx - viewW / 2) / zoom + x, y: (sy - viewH / 2) / zoom + y };
  }
}
