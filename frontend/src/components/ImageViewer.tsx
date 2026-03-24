import { useRef, useState, useEffect, useCallback } from "react";
import type { ImageMark, MarkType } from "../types";
import type { MarkResidual } from "../api/client";

interface Props {
  imageUrl: string;
  imageName: string;
  marks: ImageMark[];
  activeMarkType: MarkType;
  onMark: (imageName: string, markType: MarkType, px: number, py: number) => void;
  residuals?: MarkResidual[];
  csvProjection?: [number, number];
  computedProjection?: [number, number];
  /** Shared zoom level (multiplier of fit-to-container scale). null = fit. */
  sharedZoom: number | null;
}

interface Transform {
  x: number;
  y: number;
  scale: number;
}

export default function ImageViewer({
  imageUrl,
  imageName,
  marks,
  activeMarkType,
  onMark,
  residuals = [],
  csvProjection,
  computedProjection,
  sharedZoom,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fitScaleRef = useRef(1);
  const transformRef = useRef<Transform>({ x: 0, y: 0, scale: 1 });
  const rafRef = useRef(0);

  const [dragging, setDragging] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const [imageLoaded, setImageLoaded] = useState(false);

  // ── Apply current transform to DOM elements ──────────────────────────────
  const applyTransform = useCallback(() => {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!img || !canvas || !container) return;

    const t = transformRef.current;

    // GPU-composited CSS transform on the image — zero repaint cost
    img.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.scale})`;

    // Lightweight canvas overlay — only marks/crosshairs, no image data
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (canvas.width !== cw) canvas.width = cw;
    if (canvas.height !== ch) canvas.height = ch;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, cw, ch);
    ctx.save();
    ctx.translate(t.x, t.y);
    ctx.scale(t.scale, t.scale);

    const r = 6 / t.scale;
    const lw = 1.5 / t.scale;

    // ── Blue X: target CSV coordinates ──
    if (csvProjection) {
      const [cx, cy] = csvProjection;
      const s = r * 2;
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = lw * 1.2;
      ctx.beginPath();
      ctx.moveTo(cx - s, cy - s);
      ctx.lineTo(cx + s, cy + s);
      ctx.moveTo(cx + s, cy - s);
      ctx.lineTo(cx - s, cy + s);
      ctx.stroke();
    }

    // ── Green crosshair: computed/triangulated position ──
    if (computedProjection) {
      const [cx, cy] = computedProjection;
      const s = r * 2.5;
      ctx.strokeStyle = "#22c55e";
      ctx.lineWidth = lw * 1.2;
      ctx.beginPath();
      ctx.moveTo(cx - s, cy);
      ctx.lineTo(cx + s, cy);
      ctx.moveTo(cx, cy - s);
      ctx.lineTo(cx, cy + s);
      ctx.stroke();
      const d = r * 0.8;
      ctx.beginPath();
      ctx.moveTo(cx, cy - d);
      ctx.lineTo(cx + d, cy);
      ctx.lineTo(cx, cy + d);
      ctx.lineTo(cx - d, cy);
      ctx.closePath();
      ctx.fillStyle = "rgba(34, 197, 94, 0.6)";
      ctx.fill();
      ctx.stroke();
    }

    // ── Yellow crosshair: user marks ──
    const myMarks = marks.filter((m) => m.image_name === imageName);
    for (const mark of myMarks) {
      const isBase = mark.mark_type === "base";
      const s = r * 1.8;

      if (isBase) {
        ctx.strokeStyle = "#eab308";
        ctx.lineWidth = lw;
        ctx.beginPath();
        ctx.moveTo(mark.pixel_x - s, mark.pixel_y);
        ctx.lineTo(mark.pixel_x + s, mark.pixel_y);
        ctx.moveTo(mark.pixel_x, mark.pixel_y - s);
        ctx.lineTo(mark.pixel_x, mark.pixel_y + s);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(mark.pixel_x, mark.pixel_y, r * 0.6, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(234, 179, 8, 0.7)";
        ctx.fill();
      } else {
        ctx.beginPath();
        ctx.moveTo(mark.pixel_x, mark.pixel_y - r);
        ctx.lineTo(mark.pixel_x - r, mark.pixel_y + r);
        ctx.lineTo(mark.pixel_x + r, mark.pixel_y + r);
        ctx.closePath();
        ctx.fillStyle = "rgba(239, 68, 68, 0.8)";
        ctx.strokeStyle = "#dc2626";
        ctx.fill();
        ctx.lineWidth = lw;
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(mark.pixel_x - s, mark.pixel_y);
        ctx.lineTo(mark.pixel_x + s, mark.pixel_y);
        ctx.moveTo(mark.pixel_x, mark.pixel_y - s);
        ctx.lineTo(mark.pixel_x, mark.pixel_y + s);
        ctx.strokeStyle = "rgba(255,255,255,0.5)";
        ctx.lineWidth = 0.8 / t.scale;
        ctx.stroke();
      }

      const res = residuals.find(
        (rv) =>
          rv.image_name === imageName &&
          rv.mark_type === mark.mark_type &&
          Math.abs(rv.pixel_x - mark.pixel_x) < 0.5 &&
          Math.abs(rv.pixel_y - mark.pixel_y) < 0.5
      );

      if (res?.ground_deviation_m != null) {
        const dev = res.ground_deviation_m;
        const circleColor =
          dev < 0.03 ? "#22c55e" : dev < 0.1 ? "#eab308" : "#ef4444";
        const ppm = res.pixels_per_meter;
        const circleR = ppm != null
          ? Math.max(r * 1.5, dev * ppm)
          : Math.max(r * 1.5, r * 4);

        ctx.beginPath();
        ctx.arc(mark.pixel_x, mark.pixel_y, circleR, 0, Math.PI * 2);
        ctx.fillStyle = circleColor + "20";
        ctx.fill();
        ctx.strokeStyle = circleColor;
        ctx.lineWidth = lw;
        ctx.stroke();

        ctx.font = `${Math.max(10, 12 / t.scale)}px monospace`;
        ctx.fillStyle = circleColor;
        ctx.fillText(
          `${(dev * 1000).toFixed(0)}mm`,
          mark.pixel_x + circleR + r,
          mark.pixel_y - r,
        );
      }

      if (res?.reprojection_px != null) {
        const rpx = res.reprojection_px;
        const indicatorColor =
          rpx < 2 ? "#22c55e" : rpx < 5 ? "#eab308" : "#ef4444";
        ctx.font = `${Math.max(10, 12 / t.scale)}px monospace`;
        ctx.fillStyle = indicatorColor;
        ctx.fillText(
          `${rpx.toFixed(1)}px`,
          mark.pixel_x + r * 2,
          mark.pixel_y - r * 2,
        );
      }
    }

    ctx.restore();
  }, [marks, imageName, residuals, csvProjection, computedProjection]);

  // Schedule a single rAF draw
  const scheduleRedraw = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(applyTransform);
  }, [applyTransform]);

  // Redraw when overlays change
  useEffect(() => {
    scheduleRedraw();
  }, [scheduleRedraw]);

  // ── Image load ────────────────────────────────────────────────────────────
  function handleImageLoad() {
    const img = imgRef.current;
    const container = containerRef.current;
    if (!img || !container) return;

    setImageLoaded(true);
    const scale = Math.min(
      container.clientWidth / img.naturalWidth,
      container.clientHeight / img.naturalHeight
    );
    fitScaleRef.current = scale;
    transformRef.current = {
      x: (container.clientWidth - img.naturalWidth * scale) / 2,
      y: (container.clientHeight - img.naturalHeight * scale) / 2,
      scale,
    };
    scheduleRedraw();
  }

  // ── Shared zoom: centre on CSV projection at requested level ─────────────
  useEffect(() => {
    if (sharedZoom == null || !imgRef.current) return;
    const container = containerRef.current;
    if (!container) return;

    const scale = fitScaleRef.current * sharedZoom;
    const img = imgRef.current;
    const focusX = csvProjection ? csvProjection[0] : img.naturalWidth / 2;
    const focusY = csvProjection ? csvProjection[1] : img.naturalHeight / 2;

    transformRef.current = {
      scale,
      x: container.clientWidth / 2 - focusX * scale,
      y: container.clientHeight / 2 - focusY * scale,
    };
    scheduleRedraw();
  }, [sharedZoom, csvProjection, scheduleRedraw]);

  // ── Click to mark ─────────────────────────────────────────────────────────
  function handleClick(e: React.MouseEvent) {
    if (dragging) return;
    const container = containerRef.current!;
    const rect = container.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const t = transformRef.current;
    const px = (cx - t.x) / t.scale;
    const py = (cy - t.y) / t.scale;
    onMark(imageName, activeMarkType, px, py);
  }

  // ── Pan ────────────────────────────────────────────────────────────────────
  function handleMouseDown(e: React.MouseEvent) {
    if (e.button === 1 || e.button === 2 || e.shiftKey) {
      setDragging(true);
      const t = transformRef.current;
      dragStartRef.current = { x: e.clientX - t.x, y: e.clientY - t.y };
      e.preventDefault();
    }
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (dragging) {
      transformRef.current = {
        ...transformRef.current,
        x: e.clientX - dragStartRef.current.x,
        y: e.clientY - dragStartRef.current.y,
      };
      scheduleRedraw();
    }
  }

  function handleMouseUp() {
    setDragging(false);
  }

  // ── Zoom (mouse wheel) ────────────────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      e.stopPropagation();
      const rect = container!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;

      const t = transformRef.current;
      transformRef.current = {
        scale: t.scale * factor,
        x: mx - (mx - t.x) * factor,
        y: my - (my - t.y) * factor,
      };
      scheduleRedraw();
    }

    container.addEventListener("wheel", onWheel, { passive: false });
    return () => container.removeEventListener("wheel", onWheel);
  }, [scheduleRedraw]);

  // Clean up pending rAF on unmount
  useEffect(() => {
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  const myMarks = marks.filter((m) => m.image_name === imageName);
  const topCount = myMarks.filter((m) => m.mark_type === "base").length;
  const tipCount = myMarks.filter((m) => m.mark_type === "tip").length;

  return (
    <div
      className="image-viewer-container"
      ref={containerRef}
      style={{ overflow: "hidden" }}
      onClick={handleClick}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="image-viewer-header">
        <span>{imageName}</span>
        <span>
          Top:{topCount} Tip:{tipCount}
        </span>
      </div>
      {/* Drone image — zoomed/panned via CSS transform (GPU-composited) */}
      <img
        ref={imgRef}
        src={imageUrl}
        onLoad={handleImageLoad}
        draggable={false}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          transformOrigin: "0 0",
          willChange: "transform",
          pointerEvents: "none",
          display: imageLoaded ? "block" : "none",
        }}
      />
      {/* Canvas overlay — marks and crosshairs only (lightweight) */}
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          cursor: dragging ? "grabbing" : "crosshair",
        }}
      />
    </div>
  );
}
