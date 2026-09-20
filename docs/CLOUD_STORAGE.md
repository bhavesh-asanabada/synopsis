# Google Drive and OneDrive storage

Open **Settings & backup → Cloud document storage**. Connect either or both providers, choose **Save new documents to**, and click **Apply storage destination**. These controls save immediately. Save other preference edits before connecting: provider sign-in opens in the same tab.

New documents uploaded from the library or chat, and watched-folder imports, are copied to the selected cloud folder in the background. A local original remains in the configured upload folder for OCR, reading, and backups. This is one-way storage of original documents: notes, metadata, conversations, and edits are not synchronized across devices. One cloud destination is active for new documents at a time.

## Google Drive

1. In Google Cloud, create/select a project, enable the Drive API, and configure the OAuth consent screen. If using a test audience, include your Google account.
2. Create an OAuth client of type **Web application**. Register the **exact redirect URI shown in Synopsis**, for example `http://127.0.0.1:5001/api/connectors/google/callback`.
3. Enter the client ID and client secret in Synopsis, choose a folder name, and click **Connect Google Drive**. Complete provider consent.
4. Back in Synopsis, select Google Drive as the destination and click **Apply storage destination**.

Synopsis requests `drive.file` access and offline access. Each connection creates a dedicated folder with the chosen name. Reconnecting creates a new folder and keeps the previous folder. Google describes the prerequisites and authorization process in its [web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server).

## OneDrive

1. Register an application in Microsoft Entra with the sign-in audience matching your account: personal Microsoft accounts, work/school accounts, or both. Create a client secret and copy its **value**.
2. Configure a **Web** redirect URI using the exact value shown in Synopsis, for example `http://localhost:5001/api/connectors/onedrive/callback`. Use delegated Microsoft Graph `Files.ReadWrite` permission; Synopsis also requests `offline_access`. Organization policy may require administrator consent.
3. Enter the application client ID and secret in Synopsis. Leave tenant as `common` for an application accepting the corresponding account types, or use its specific tenant ID for a single-tenant registration. Choose a folder name and click **Connect OneDrive**.
4. After consent, select OneDrive as the destination and click **Apply storage destination**. Synopsis uses or creates that folder in the signed-in user's default drive.

See Microsoft's [application registration guide](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) and [authorization-code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow). This connector targets personal/default business OneDrive, not SharePoint site libraries or sovereign-cloud endpoints.

If the portal rejects an HTTP `127.0.0.1` redirect, open Synopsis at `http://localhost:5001` (or your configured port) **before connecting**, and register the localhost redirect shown there. Keep the same host throughout sign-in so the browser's connection cookie is returned. Microsoft documents [loopback redirect restrictions](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url), including the manifest configuration required for HTTP IP-literal redirects.

## Status and recovery

A document's **Overview → Cloud storage** shows Waiting to upload, Uploading, Saved, or Needs attention. Use **Open cloud copy** to inspect a completed upload. Choose **Retry cloud upload** after fixing a connection or quota problem. Restarting Synopsis resumes queued/interrupted transfers. Failed transfers wait for an explicit retry, while local OCR and reading remain available.

**Save to cloud** copies an existing document to the currently selected destination. Changing the default does not move previous files or redirect queued transfers. After disconnecting/reconnecting, use Save to cloud to explicitly target the new connection; old retries cannot silently upload into another account. A document displays the latest targeted cloud copy; earlier copies remain in their drives.

Google uploads use resumable sessions and a persisted pre-generated file ID, then verify byte count and MD5. Repeated attempts reuse the ID. See [Google's upload guide](https://developers.google.com/workspace/drive/api/guides/manage-uploads). OneDrive uses a stable, unique filename prefixed with the reference ID and verifies the returned byte count. The application's 100 MB document limit fits within Microsoft's [single-request upload limit](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0). A failed OneDrive request retries the complete file at the same path.

Disconnect removes account tokens locally, cancels pending transfers for that account, and changes its active destination to local storage. OAuth application configuration is retained. Disconnecting, trashing, or permanently deleting local references **does not delete cloud copies**. Manage those copies directly in the provider. Revoke the application's grant in your provider account if you want to remove consent there too.

Credentials and refresh tokens are stored in the local SQLite database, unencrypted, and excluded from exported ZIP backups and browser responses. Backups include local originals and cloud-copy status/links. Restoring a backup leaves connectors disconnected and incomplete cloud transfers paused. A raw database copy includes credentials, unlike an exported ZIP.

The connector tests simulate provider consent and HTTP responses, including token refresh and lost upload responses. Real account consent, tenant policies, quota, and service availability still need verification with your registered applications. No account credentials or cloud subscriptions are bundled with Synopsis.
