# Android Static/Dynamic Analysis Plan

Target app: `ASTRA Cockpit`, package `de.astra_software.astracockpit`.

## Static Analysis

1. Obtain APK from a connected device or local trusted source:
   ```sh
   adb shell pm path de.astra_software.astracockpit
   adb pull /path/from/pm astra-cockpit.apk
   ```
2. Keep the APK out of git; `.gitignore` excludes `*.apk`.
3. Decompile:
   ```sh
   jadx -d captures/android/jadx astra-cockpit.apk
   apktool d -o captures/android/apktool astra-cockpit.apk
   ```
4. Search for:
   - `astra-cloud.com`
   - `readyxnet`
   - `http://` / `https://`
   - `Authorization`, `Bearer`, `session`, `cookie`, `csrf`
   - Retrofit/OkHttp clients and interceptors
   - certificate pinning logic
   - JSON model classes for meter, tariff, power, energy, billing periods.

## Dynamic Analysis

Use dynamic capture only if static analysis does not reveal enough:

1. Run app on test device/emulator.
2. Configure an HTTPS proxy such as mitmproxy.
3. Install the proxy CA if the app honors user CAs.
4. If certificate pinning blocks capture, document the pinning location first; use Frida only with explicit approval.

## Output

Add sanitized findings to `docs/api.md`, clearly marking app-only endpoints and any fields not visible in the web portal.

## Current Findings

- Confirmed native API endpoint:
  `https://astra-cloud.com/readyxnet/source/login/csandroid.php`.
- The app signs form POST actions with `s_cs=md5("SNAFU" + action + timestamp)`.
- The login/session id is `md5(username + md5(password))`.
- Responses append `md5(payload)` as the final 32 characters.
- Main actions and JSON schemas are documented in `docs/api.md`.
