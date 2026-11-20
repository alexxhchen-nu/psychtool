import { Composition } from "remotion";
import { CursorCastEnsemble, CURSOR_CAST_ENSEMBLE_DURATION } from "./interaction/collab-cursor-moves/CursorCastEnsemble";
import { PsychtoolExplain, PSYCHTOOL_EXPLAIN_DURATION } from "./PsychtoolExplain";

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="PsychtoolExplain"
        component={PsychtoolExplain}
        durationInFrames={PSYCHTOOL_EXPLAIN_DURATION}
        fps={30}
        width={1920}
        height={1080}
      />
      <Composition
        id="PsychtoolPromo"
        component={CursorCastEnsemble}
        durationInFrames={CURSOR_CAST_ENSEMBLE_DURATION}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
