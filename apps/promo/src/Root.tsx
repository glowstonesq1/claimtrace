import { Composition } from "remotion";
import { Promo, PromoProps } from "./Promo";
import { DURATION, FPS } from "./timeline";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ClaimTracePromo"
    component={Promo}
    durationInFrames={DURATION}
    fps={FPS}
    width={1920}
    height={1080}
    // bgm: true renders the music bed; false renders sound effects only.
    defaultProps={{ bgm: true } satisfies PromoProps}
  />
);
