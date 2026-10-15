# 3D Comic Mobile Wrapper (Android / iOS)

This directory contains stub projects for wrapping your Modern 3D Viewer into a mobile app using WebView.

## Structure
- `android/`: Android Studio project stub (Java)
- `ios/`: Xcode project stub (Swift)

## Deployment Instructions
1. Build your 3D Comic using the "Modern Web" pipeline.
2. Copy the entire contents of the `Book/` (or your output root) into:
   - Android: `android/app/src/main/assets/www/`
   - iOS: `ios/ComicViewer/www/`
3. Open the respective project in Android Studio or Xcode.
4. Build and Run on your device.

Note: Ensure that `scene.glb` and `pages/index.json` are included in the assets.
