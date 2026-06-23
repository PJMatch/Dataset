# PJMatch: Dataset Recorder

A dedicated React Native (Expo) mobile application built for recording the Polish Sign Language (PJM) dataset. 

This application was created to streamline the recording process for actors and ensure data privacy. It sends video files directly to a secure server, completely bypassing the device's local storage and gallery.

## Key Features

- **Direct Server Upload:** Videos and paired `.json` metadata files are generated on the fly and sent straight to the server.
- **Background Upload Queue:** Record continuously without waiting. Uploads are queued in the background, allowing uninterrupted work even on slow network connections.
- **Bluetooth Remote Support:** Navigate and record hands-free to eliminate camera shake on the tripod.
- **Auto-Next:** The app automatically advances to the next sentence in the database pool after a successful recording.

## Getting Started

### Prerequisites
Make sure you have Node.js and npm installed on your machine.

### Installation & Running Locally

1. Install dependencies:
   ```bash
   npm install
   ```

2. Start the Expo development server:
   ```bash
   npx expo start
   ```

### Important Note on Permissions
If you are building the APK or running the app on a physical Android device, the app **does not automatically prompt for camera permissions**. Before using the app, you must go to your phone's **Settings -> Apps -> Dataset Recorder -> Permissions** and manually grant **Camera** access. The app will not function without this step.

## Built With
- [React Native](https://reactnative.dev/)
- [Expo](https://expo.dev/)
