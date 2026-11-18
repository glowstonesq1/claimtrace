import { Config } from "@remotion/cli/config";

// Offline machines can point Remotion at an installed headless Chromium instead of downloading one:
//   REMOTION_BROWSER_EXECUTABLE=/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell
if (process.env.REMOTION_BROWSER_EXECUTABLE) {
  Config.setBrowserExecutable(process.env.REMOTION_BROWSER_EXECUTABLE);
}
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
