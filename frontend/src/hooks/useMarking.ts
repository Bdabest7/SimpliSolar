import { useState, useCallback } from "react";
import type { MarkSet, ImageMark, MarkType } from "../types";
import { getMarks, addMark, clearMarks, replaceMarks } from "../api/client";

export function useMarking(projectId: string, targetId: string) {
  const [markSet, setMarkSet] = useState<MarkSet>({ target_id: targetId, marks: [] });
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const ms = await getMarks(projectId, targetId);
      setMarkSet(ms);
    } finally {
      setLoading(false);
    }
  }, [projectId, targetId]);

  const add = useCallback(
    async (imageName: string, markType: MarkType, px: number, py: number) => {
      const mark: ImageMark = {
        image_name: imageName,
        mark_type: markType,
        pixel_x: px,
        pixel_y: py,
      };
      const ms = await addMark(projectId, targetId, mark);
      setMarkSet(ms);
      return ms;
    },
    [projectId, targetId]
  );

  const clear = useCallback(async () => {
    const ms = await clearMarks(projectId, targetId);
    setMarkSet(ms);
  }, [projectId, targetId]);

  const replace = useCallback(
    async (marks: ImageMark[]) => {
      const ms = await replaceMarks(projectId, targetId, {
        target_id: targetId,
        marks,
      });
      setMarkSet(ms);
    },
    [projectId, targetId]
  );

  return { markSet, loading, refresh, add, clear, replace };
}
