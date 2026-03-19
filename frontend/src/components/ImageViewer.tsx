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
}

export default function ImageViewer({
  imageUrl,
  imageName,
  marks,
  activeMarkType,
  onMark,
  residuals = [],
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [imageLoaded, setImageLoaded] = useState(false);

  // Load image
  useEffect(() => {
    const img = new Image();
    img.src = imageUrl;
    img.onload = () => {
      imageRef.current = img;
      setImageLoaded(true);
      // Fit image to container
      const container = containerRef.current;
      if (container) {
        const scale = Math.min(
          container.clientWidth / img.width,
          container.clientHeight / img.height
        );
        setTransform({
          x: (container.clientWidth - img.width * scale) / 2,
          y: (container.clientHeight - img.height * scale) / 2,
          scale,
        });
      }
    };
  }, [imageUrl]);

  // Render
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const container = containerRef.current!;
    canvas.width = container.clientWidth;
    canvas.height = container.clientHeight;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(transform.scale, transform.scale);

    ctx.drawImage(img, 0, 0);

    // Draw marks
    const myMarks = marks.filter((m) => m.image_name === imageName);
    for (const mark of myMarks) {
      const isBase = mark.mark_type === "base";
      ctx.beginPath();
      const r = 6 / transform.scale;
      if (isBase) {
        ctx.arc(mark.pixel_x, mark.pixel_y, r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(34, 197, 94, 0.8)";
        ctx.strokeStyle = "#16a34a";
      } else {
        // Triangle for tip
        ctx.moveTo(mark.pixel_x, mark.pixel_y - r);
        ctx.lineTo(mark.pixel_x - r, mark.pixel_y + r);
        ctx.lineTo(mark.pixel_x + r, mark.pixel_y + r);
        ctx.closePath();
        ctx.fillStyle = "rgba(239, 68, 68, 0.8)";
        ctx.strokeStyle = "#dc2626";
      }
      ctx.fill();
      ctx.lineWidth = 1.5 / transform.scale;
      ctx.stroke();

      // Crosshair
      ctx.beginPath();
      ctx.moveTo(mark.pixel_x - r * 2, mark.pixel_y);
      ctx.lineTo(mark.pixel_x + r * 2, mark.pixel_y);
      ctx.moveTo(mark.pixel_x, mark.pixel_y - r * 2);
      ctx.lineTo(mark.pixel_x, mark.pixel_y + r * 2);
      ctx.strokeStyle = "rgba(255,255,255,0.6)";
      ctx.lineWidth = 0.8 / transform.scale;
      ctx.stroke();

      // Residual indicator for this mark
      const res = residuals.find(
        (res) =>
          res.image_name === imageName &&
          res.mark_type === mark.mark_type &&
          Math.abs(res.pixel_x - mark.pixel_x) < 0.5 &&
          Math.abs(res.pixel_y - mark.pixel_y) < 0.5
      );

      // Tip marks with ground_deviation_m: draw confidence circle
      if (res?.ground_deviation_m != null) {
        const dev = res.ground_deviation_m;
        const circleColor =
          dev < 0.03
            ? "#22c55e"   // green  — <30mm
            : dev < 0.1
            ? "#eab308"   // yellow — 30–100mm
            : "#ef4444";  // red    — >100mm

        // Convert ground deviation (metres) to image pixels using camera GSD.
        // pixels_per_meter = focal_length_px / altitude_above_ground
        // Circle radius in image pixels = deviation_m * pixels_per_meter
        const ppm = res.pixels_per_meter;
        const circleR = ppm != null
          ? Math.max(r * 1.5, dev * ppm)
          : Math.max(r * 1.5, r * 4); // fallback: fixed size if no ppm

        ctx.beginPath();
        ctx.arc(mark.pixel_x, mark.pixel_y, circleR, 0, Math.PI * 2);
        ctx.fillStyle = circleColor + "20"; // very translucent fill
        ctx.fill();
        ctx.strokeStyle = circleColor;
        ctx.lineWidth = 1.5 / transform.scale;
        ctx.stroke();

        // Label with deviation in mm
        ctx.font = `${Math.max(10, 12 / transform.scale)}px monospace`;
        ctx.fillStyle = circleColor;
        ctx.fillText(
          `${(dev * 1000).toFixed(0)}mm`,
          mark.pixel_x + circleR + r,
          mark.pixel_y - r,
        );
      }

      // Base marks (or tip fallback): reprojection line + crosshair
      if (res?.projected_x != null && res.projected_y != null && res.reprojection_px != null) {
        const rpx = res.reprojection_px;
        const indicatorColor =
          rpx < 2
            ? "#22c55e"   // green  — well constrained
            : rpx < 5
            ? "#eab308"   // yellow — moderate
            : "#ef4444";  // red    — poor

        const px = res.projected_x;
        const py = res.projected_y;
        const cr = 4 / transform.scale;

        // Line from original mark to reprojected point
        ctx.beginPath();
        ctx.moveTo(mark.pixel_x, mark.pixel_y);
        ctx.lineTo(px, py);
        ctx.strokeStyle = indicatorColor;
        ctx.lineWidth = 1 / transform.scale;
        ctx.stroke();

        // Small crosshair at reprojected location
        ctx.beginPath();
        ctx.moveTo(px - cr, py);
        ctx.lineTo(px + cr, py);
        ctx.moveTo(px, py - cr);
        ctx.lineTo(px, py + cr);
        ctx.strokeStyle = indicatorColor;
        ctx.lineWidth = 1.5 / transform.scale;
        ctx.stroke();

        // Label with reprojection error in pixels
        ctx.font = `${Math.max(10, 12 / transform.scale)}px monospace`;
        ctx.fillStyle = indicatorColor;
        ctx.fillText(
          `${rpx.toFixed(1)}px`,
          mark.pixel_x + r * 2,
          mark.pixel_y - r * 2,
        );
      }
    }

    ctx.restore();
  }, [transform, marks, imageName, imageLoaded, residuals]);

  useEffect(() => {
    render();
  }, [render]);

  // Click to mark
  function handleClick(e: React.MouseEvent) {
    if (dragging) return;
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    const px = (cx - transform.x) / transform.scale;
    const py = (cy - transform.y) / transform.scale;
    onMark(imageName, activeMarkType, px, py);
  }

  // Pan
  function handleMouseDown(e: React.MouseEvent) {
    if (e.button === 1 || e.button === 2 || e.shiftKey) {
      setDragging(true);
      setDragStart({ x: e.clientX - transform.x, y: e.clientY - transform.y });
      e.preventDefault();
    }
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (dragging) {
      setTransform((t) => ({
        ...t,
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      }));
    }
  }

  function handleMouseUp() {
    setDragging(false);
  }

  // Zoom — native wheel listener so preventDefault actually stops page scroll
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    function onWheel(e: WheelEvent) {
      e.preventDefault();
      e.stopPropagation();
      const rect = canvas!.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;

      setTransform((t) => ({
        scale: t.scale * factor,
        x: mx - (mx - t.x) * factor,
        y: my - (my - t.y) * factor,
      }));
    }

    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, []);

  const myMarks = marks.filter((m) => m.image_name === imageName);
  const topCount = myMarks.filter((m) => m.mark_type === "base").length;
  const tipCount = myMarks.filter((m) => m.mark_type === "tip").length;

  return (
    <div className="image-viewer-container" ref={containerRef}>
      <div className="image-viewer-header">
        <span>{imageName}</span>
        <span>
          Top:{topCount} Tip:{tipCount}
        </span>
      </div>
      <canvas
        ref={canvasRef}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%", cursor: dragging ? "grabbing" : "crosshair" }}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onContextMenu={(e) => e.preventDefault()}
      />
    </div>
  );
}
