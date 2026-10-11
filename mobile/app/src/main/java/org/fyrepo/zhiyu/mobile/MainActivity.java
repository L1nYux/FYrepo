package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ColorMatrix;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.DashPathEffect;
import android.os.SystemClock;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.URLUtil;
import android.net.http.SslError;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.ScrollView;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.net.URLEncoder;
import java.util.regex.Pattern;
import java.util.regex.Matcher;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A small phone shell. Sessions and all permissions stay with the existing server. */
public final class MainActivity extends Activity {
    private static final int GREEN = Color.rgb(7, 160, 90);
    private int accentColor = GREEN;
    private static final int INK = Color.rgb(31, 35, 40);
    private static final int PAPER = Color.rgb(247, 248, 250);
    private static final int PICK_FILES = 10, SAVE_FILE = 11, SAVE_CHAT = 13, TAKE_PHOTO = 14, SCAN_CODE = 15;
    private static final String DEFAULT_SERVER = "http://47.117.89.248";
    private static final String[] LABELS = {"消息", "工作台", "AI", "发现", "我"};
    private static final String[] ROUTES = {"/messages/social/", "/workspace/", "/assistant/", "/discover/", "/me/"};
    private WebView web;
    private OfflinePages offlinePages;
    private int navigationGeneration;
    private MobileUpdater updater;
    private LinearLayout root, toolbar, tabs, overlay;
    private TextView title, back;
    private final TextView[] tabLabels = new TextView[5];
    private final TabIcon[] icons = new TabIcon[5];
    private ValueCallback<Uri[]> filePicker;
    private Uri cameraOutput;
    private TextView more;
    private FileDownloads fileDownloads;
    private String origin, css, script, failedUrl, pendingDownload, pendingCookie;
    private boolean keyboardOpen, chatPage, pageError, contentReady, nativeLogin, resetHistory;
    private int currentTab, loginGeneration, reportedHeight=-1;
    private boolean reportedKeyboard;
    private ImageView previousPage;
    private Bitmap brandBitmap;
    private LoadingStrip loadingStrip;
    private View tabDivider;
    private String presentedUrl;
    private String backupPage;
    private Uri backupDestination;
    private final StringBuilder backupText = new StringBuilder();
    private final ExecutorService files = Executors.newSingleThreadExecutor();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        SharedPreferences settings = getSharedPreferences("connection", MODE_PRIVATE);
        origin = settings.getString("origin", DEFAULT_SERVER);
        try { origin = normalizeOrigin(origin); }
        catch (Exception ignored) { origin = DEFAULT_SERVER; }
        try {
            css = readAsset("mobile.css") + "\n" + readAsset("phone-layout.css");
            script = readAsset("phone-interactions.js") + "\n" + readAsset("mobile.js")
                + "\n" + readAsset("phone-assistant.js") + "\n" + readAsset("local-chat.js") + "\n" + readAsset("phone-layout.js");
        } catch (Exception e) { throw new IllegalStateException("Missing mobile interface", e); }
        BitmapFactory.Options bitmapOptions = new BitmapFactory.Options(); bitmapOptions.inScaled = false;
        brandBitmap = BitmapFactory.decodeResource(getResources(), R.drawable.brand, bitmapOptions);
        createLayout();
        offlinePages = new OfflinePages(this, address -> web.post(() -> {
            if (!address.equals(web.getUrl()) || nativeLogin || pageError) return;
            web.evaluateJavascript("Boolean(window.zhiyuPageEdited) || Boolean(document.querySelector('.conversation-composer textarea, #assistant-input')?.value.trim()) || Boolean(document.querySelector('#assistant-stop:not([hidden])')) || Array.from(document.querySelectorAll('input[type=file]')).some(i=>i.files.length)", dirty -> {
                if (address.equals(web.getUrl()) && "false".equals(dirty)) web.reload();
            });
        }));
        setupBrowser();
        updater = new MobileUpdater(this);
        web.postDelayed(() -> updater.check(false), 8000);
        if (state == null || web.restoreState(state) == null) web.loadUrl(origin + ROUTES[0]);
        openNotification(getIntent());
        web.postDelayed(badgeRefresh,8000);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private LinearLayout vertical() {
        LinearLayout view = new LinearLayout(this);
        view.setOrientation(LinearLayout.VERTICAL);
        return view;
    }
    private TextView text(String value, int size) {
        TextView result = new TextView(this);
        result.setText(value); result.setTextSize(size); result.setTextColor(INK);
        result.setGravity(Gravity.CENTER_VERTICAL);
        return result;
    }
    private TextView button(String label, View.OnClickListener action) {
        TextView view = text(label, 15);
        view.setGravity(Gravity.CENTER); view.setMinHeight(dp(46));
        view.setPadding(dp(18), dp(8), dp(18), dp(8));
        GradientDrawable background = new GradientDrawable();
        background.setColor(GREEN); background.setCornerRadius(dp(12));
        view.setBackground(background); view.setTextColor(Color.WHITE);
        view.setOnClickListener(action);
        return view;
    }

    private void createLayout() {
        root = vertical(); root.setBackgroundColor(PAPER); root.setFitsSystemWindows(true);
        toolbar = new LinearLayout(this); toolbar.setGravity(Gravity.CENTER_VERTICAL);
        toolbar.setPadding(dp(8), 0, dp(8), 0); toolbar.setBackgroundColor(PAPER);
        back = text("‹", 30); back.setGravity(Gravity.CENTER); back.setContentDescription("返回");
        back.setOnClickListener(v -> handleBack());
        toolbar.addView(back, new LinearLayout.LayoutParams(dp(44), dp(50)));
        title = text("消息", 19); title.setTypeface(null, Typeface.BOLD);
        toolbar.addView(title, new LinearLayout.LayoutParams(0, dp(50), 1));
        more = text("⋯", 28); more.setGravity(Gravity.CENTER);
        more.setContentDescription("更多"); more.setOnClickListener(v -> {
            if (isRootPage(web.getUrl()) && currentTab == 0)
                web.evaluateJavascript("document.querySelector('[data-contact-add-open]')?.click()", null);
            else showMenu();
        });
        toolbar.addView(more, new LinearLayout.LayoutParams(dp(44), dp(50)));
        root.addView(toolbar);
        FrameLayout stage = new FrameLayout(this);
        root.addView(stage, new LinearLayout.LayoutParams(-1, 0, 1));
        web = new WebView(this); web.setBackgroundColor(Color.WHITE);
        stage.addView(web, new FrameLayout.LayoutParams(-1, -1));
        overlay = vertical(); overlay.setGravity(Gravity.CENTER); overlay.setBackgroundColor(PAPER);
        overlay.setPadding(dp(32), dp(20), dp(32), dp(20));
        stage.addView(overlay, new FrameLayout.LayoutParams(-1, -1));
        previousPage = new ImageView(this); previousPage.setScaleType(ImageView.ScaleType.FIT_XY);
        previousPage.setVisibility(View.GONE); stage.addView(previousPage, new FrameLayout.LayoutParams(-1, -1));
        loadingStrip = new LoadingStrip(); loadingStrip.setVisibility(View.GONE);
        FrameLayout.LayoutParams loadingParams = new FrameLayout.LayoutParams(-1, dp(2), Gravity.TOP);
        stage.addView(loadingStrip, loadingParams);
        tabs = new LinearLayout(this); tabs.setBackgroundColor(PAPER);
        tabs.setPadding(0, dp(4), 0, dp(3));
        for (int i = 0; i < LABELS.length; i++) {
            final int index = i;
            LinearLayout cell = vertical(); cell.setGravity(Gravity.CENTER);
            cell.setContentDescription(LABELS[i]); cell.setOnClickListener(v -> switchTab(index));
            icons[i] = new TabIcon(i); cell.addView(icons[i], new LinearLayout.LayoutParams(dp(28), dp(28)));
            tabLabels[i] = text(LABELS[i], 11); tabLabels[i].setGravity(Gravity.CENTER);
            cell.addView(tabLabels[i], new LinearLayout.LayoutParams(-1, dp(20)));
            tabs.addView(cell, new LinearLayout.LayoutParams(0, dp(54), 1));
        }
        View divider = new View(this); tabDivider = divider; divider.setBackgroundColor(Color.rgb(230, 233, 235));
        root.addView(divider, new LinearLayout.LayoutParams(-1, dp(1)));
        root.addView(tabs);
        setContentView(root);
        root.getViewTreeObserver().addOnGlobalLayoutListener(() -> {
            Rect visible = new Rect(); root.getWindowVisibleDisplayFrame(visible);
            android.view.WindowInsets insets = root.getRootWindowInsets();
            boolean open = android.os.Build.VERSION.SDK_INT >= 30 && insets != null
                ? insets.isVisible(android.view.WindowInsets.Type.ime())
                : root.getHeight() - visible.height() > Math.max(dp(180),root.getHeight()/4);
            if (open != keyboardOpen) { keyboardOpen = open; updateBars(web.getUrl()); }
            int measured=Math.round(web.getHeight()/getResources().getDisplayMetrics().density);
            if (trusted(web.getUrl()) && (measured!=reportedHeight || keyboardOpen!=reportedKeyboard)) {reportedHeight=measured;reportedKeyboard=keyboardOpen;web.post(() -> web.evaluateJavascript(
                "window.zhiyuPhoneViewport?.(" + (web.getHeight()/getResources().getDisplayMetrics().density) + "," + keyboardOpen + ")", null));}
        });
        showLoading();
    }

    @SuppressWarnings("deprecation") private void setupBrowser() {
        fileDownloads=new FileDownloads(this);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSafeBrowsingEnabled(true);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setTextZoom(100);
        settings.setUserAgentString(settings.getUserAgentString() + " ZhiyuMobile/" + BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        // No JavaScript-to-Java bridge is exposed to server content.
        web.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                String address = request.getUrl().toString(), path = request.getUrl().getPath();
                if (trusted(address)) {
                    WebResourceResponse cached=offlinePages.intercept(origin,request);
                    if(cached!=null)return cached;
                }
                if (request.isForMainFrame() || !"GET".equals(request.getMethod()) || !trusted(address)
                    || path == null || !path.startsWith("/static/") || path.contains("..") || path.contains("\\")) return null;
                // A bundled component is usable only when it matches the server's content hash.
                Matcher versioned = Pattern.compile("^(.+)\\.([a-f0-9]{12})\\.([a-z0-9]+)$").matcher(path.substring(1));
                if (!versioned.matches()) return null;
                String asset = versioned.group(1)+"."+versioned.group(3);
                byte[] component;
                try (InputStream stream=getAssets().open(asset)) {
                    ByteArrayOutputStream output=new ByteArrayOutputStream();
                    byte[] buffer=new byte[8192]; int length;
                    while((length=stream.read(buffer))!=-1)output.write(buffer,0,length);
                    component=output.toByteArray();
                    byte[] digest=java.security.MessageDigest.getInstance("MD5").digest(component);
                    StringBuilder actual=new StringBuilder();
                    for(byte value:digest)actual.append(String.format(java.util.Locale.ROOT,"%02x",value & 255));
                    if(!actual.toString().startsWith(versioned.group(2)))return null;
                } catch(Exception missing){return null;}
                String type = asset.endsWith(".css") ? "text/css" : asset.endsWith(".js") ? "application/javascript"
                    : asset.endsWith(".json") ? "application/json" : asset.endsWith(".svg") ? "image/svg+xml" : "text/plain";
                return new WebResourceResponse(type, "UTF-8", new java.io.ByteArrayInputStream(component));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                return handleNavigation(request.getUrl().toString());
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageError = false;
                if (trusted(url) && "/login/".equals(Uri.parse(url).getPath())) {
                    offlinePages.clear(origin);
                    view.stopLoading(); showLogin(); return;
                }
                nativeLogin = false; updateBars(url); showLoading();
            }
            @Override public void onPageFinished(WebView view, String url) {
                reportedHeight=-1;
                if (!trusted(url) || pageError || nativeLogin) return;
                view.evaluateJavascript("JSON.stringify({account:document.documentElement.dataset.account||'',html:document.documentElement.outerHTML})", account -> {
                    try {
                        JSONObject snapshot=new JSONObject(new org.json.JSONArray("[" + account + "]").getString(0));
                        String identifier = snapshot.getString("account");
                        if (url.equals(web.getUrl()) && identifier.matches("[1-9][0-9]*")) {
                            android.content.SharedPreferences prefs=getSharedPreferences("connection", MODE_PRIVATE);
                            prefs.edit().putString("account:" + origin, identifier).apply();
                            String selected = Uri.parse(url).getQueryParameter("ownership");
                            if ("/workspace/".equals(Uri.parse(url).getPath()) && selected != null && selected.matches("all|[1-9][0-9]*"))
                                prefs.edit().putString("reading-owner:"+origin+":"+identifier,selected).apply();
                            offlinePages.remember(origin,url,snapshot.getString("html"));
                            startMessageSync();
                            if (!prefs.getBoolean("message-permission-explained",false)) {
                                prefs.edit().putBoolean("message-permission-explained",true).apply();
                                backgroundMessages();
                            }
                        }
                    } catch (Exception ignored) { }
                });
                String injection = "(function(){var s=document.getElementById('zhiyu-phone-css');"
                    + "if(!s){s=document.createElement('style');s.id='zhiyu-phone-css';document.head.append(s);}"
                    + "s.textContent=" + JSONObject.quote(css) + ";" + script + "})()";
                view.evaluateJavascript(injection, result -> {
                    if (!pageError && !nativeLogin && url.equals(web.getUrl())) {
                        // Wait for the adapted layout to paint before uncovering it.
                        view.evaluateJavascript("window.zhiyuPhoneViewport?.("+(web.getHeight()/getResources().getDisplayMetrics().density)+","+keyboardOpen+");requestAnimationFrame(()=>requestAnimationFrame(()=>{document.documentElement.dataset.phonePainted='true';}))", ignored ->
                            web.postDelayed(() -> {
                                if (pageError || nativeLogin || !url.equals(web.getUrl())) return;
                                overlay.setVisibility(View.GONE); previousPage.setVisibility(View.GONE);
                                previousPage.setImageDrawable(null); loadingStrip.setVisibility(View.GONE);
                                web.setVisibility(View.VISIBLE); contentReady = true; presentedUrl = url;
                                if (resetHistory || isRootPage(url)) { web.clearHistory(); resetHistory = false; }
                                updateBars(url);
                            }, 48));
                    }
                });
                CookieManager.getInstance().flush();
                updateBars(url);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !nativeLogin) connectionError(request.getUrl().toString(), "暂时连接不上团队服务器。");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && !nativeLogin && response.getStatusCode() >= 500)
                    connectionError(request.getUrl().toString(), "服务器暂时不可用（" + response.getStatusCode() + "）。");
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                connectionError(view.getUrl(), "服务器 HTTPS 证书无效，请检查连接地址。");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsConfirm(WebView view,String url,String message,android.webkit.JsResult result){
                if(!trusted(url)){result.cancel();return true;}
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setNegativeButton("取消",(dialog,which)->result.cancel())
                    .setPositiveButton("确定",(dialog,which)->result.confirm())
                    .setOnCancelListener(dialog->result.cancel()).show();
                return true;
            }
            @Override public boolean onJsAlert(WebView view,String url,String message,android.webkit.JsResult result){
                if(!trusted(url)){result.cancel();return true;}
                new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("知道了",(dialog,which)->result.confirm())
                    .setOnCancelListener(dialog->result.confirm()).show();
                return true;
            }

            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!trusted(view.getUrl())) { callback.onReceiveValue(null); return true; }
                if (filePicker != null) filePicker.onReceiveValue(null);
                filePicker = callback;
                String[] accepted = params.getAcceptTypes();
                boolean images = accepted.length > 0 && java.util.Arrays.stream(accepted).allMatch(t -> t.startsWith("image/"));
                if (params.isCaptureEnabled() && images) { capturePhoto(); return true; }
                Intent intent;
                if (images && android.os.Build.VERSION.SDK_INT >= 33) {
                    intent = new Intent(params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE ? "android.provider.action.PICK_IMAGES" : "android.provider.action.PICK_IMAGES");
                    if (params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) intent.putExtra("android.provider.extra.PICK_IMAGES_MAX", 10);
                    intent.setType("image/*");
                } else {
                    intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(images ? "image/*" : "*/*");
                    if (accepted.length > 0 && !accepted[0].isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, accepted);
                    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                }
                try { startActivityForResult(intent, PICK_FILES); }
                catch (ActivityNotFoundException e) { filePicker.onReceiveValue(null); filePicker = null; toast("手机未提供文件选择器。"); }
                return true;
            }
        });
        web.setDownloadListener((url, agent, disposition, mime, length) -> {
            if (!trusted(url)) { openExternal(url); return; }
            String name=URLUtil.guessFileName(url,disposition,mime);
            fileDownloads.start(origin,getSharedPreferences("connection",MODE_PRIVATE).getString("account:"+origin,""),url,name,mime,false);
            overlay.setVisibility(View.GONE); previousPage.setVisibility(View.GONE); loadingStrip.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
        });
    }

    private void capturePhoto() {
        if (checkSelfPermission(android.Manifest.permission.CAMERA) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.CAMERA}, TAKE_PHOTO); return;
        }
        try {
            java.io.File dir = new java.io.File(getCacheDir(), "captures"); dir.mkdirs();
            // Keep only temporary captures; existing uploads have already been copied by the server.
            java.io.File[] old = dir.listFiles(); if (old != null) for (java.io.File f : old)
                if (System.currentTimeMillis()-f.lastModified() > 86400000L) f.delete();
            String name = java.util.UUID.randomUUID().toString() + ".jpg";
            cameraOutput = Uri.parse("content://" + getPackageName() + ".captures/" + name);
            Intent intent = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE)
                .putExtra(android.provider.MediaStore.EXTRA_OUTPUT, cameraOutput)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            intent.setClipData(android.content.ClipData.newRawUri("photo", cameraOutput));
            startActivityForResult(intent, TAKE_PHOTO);
        } catch (Exception e) { cameraOutput = null; if(filePicker != null) { filePicker.onReceiveValue(null); filePicker=null; } toast("无法打开相机。"); }
    }
    @Override public void onRequestPermissionsResult(int request, String[] names, int[] results) {
        super.onRequestPermissionsResult(request,names,results);
        if(request == 16){if(results.length>0&&results[0]==android.content.pm.PackageManager.PERMISSION_GRANTED)startMessageSync();else{getSharedPreferences("connection",MODE_PRIVATE).edit().putBoolean("background-messages",false).apply();toast("通知权限未开启，仍可在应用内查看提醒。");}return;}
        if(request == TAKE_PHOTO) {
            if(results.length > 0 && results[0] == android.content.pm.PackageManager.PERMISSION_GRANTED) capturePhoto();
            else { if(filePicker != null) {filePicker.onReceiveValue(null);filePicker=null;} toast("拍照需要相机权限，可在设置中开启。"); }
        }
    }

    private boolean trusted(String address) {
        if (address == null) return false;
        try {
            URI a = new URI(address), b = new URI(origin);
            return a.getUserInfo() == null && b.getScheme().equalsIgnoreCase(a.getScheme())
                && b.getHost().equalsIgnoreCase(a.getHost()) && port(a) == port(b);
        } catch (Exception e) { return false; }
    }
    private static int port(URI uri) {
        return uri.getPort() >= 0 ? uri.getPort() : ("https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80);
    }
    private static String normalizeOrigin(String value) throws Exception {
        URI uri = new URI(value.trim());
        if (!("http".equalsIgnoreCase(uri.getScheme()) || "https".equalsIgnoreCase(uri.getScheme()))
            || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null
            || uri.getFragment() != null || !(uri.getPath().isEmpty() || uri.getPath().equals("/"))
            || uri.getPort() > 65535 || uri.getPort() == 0) throw new IllegalArgumentException();
        return new URI(uri.getScheme().toLowerCase(), null, uri.getHost().toLowerCase(), uri.getPort(), null, null, null).toASCIIString();
    }
    private boolean handleNavigation(String url) {
        if (!trusted(url)) { openExternal(url); return true; }
        String path = Uri.parse(url).getPath();
        if ("/logout/".equals(path)) offlinePages.clear(origin);
        if ("/__phone_file_open__/".equals(path)) {Uri value=Uri.parse(url);String address=value.getQueryParameter("url"),name=value.getQueryParameter("name");if(trusted(web.getUrl())&&address!=null&&trusted(address)&&name!=null){String mime=android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(name.substring(name.lastIndexOf('.')+1).toLowerCase(java.util.Locale.ROOT));fileDownloads.start(origin,getSharedPreferences("connection",MODE_PRIVATE).getString("account:"+origin,""),address,name,mime,true);}return true;}
        if ("/__phone_accent__/".equals(path)) {String value=Uri.parse(url).getQueryParameter("name");String color="green".equals(value)?"#079b61":"blue".equals(value)?"#3679d5":"purple".equals(value)?"#8654c7":"orange".equals(value)?"#bf6415":"pink".equals(value)?"#c14c83":null;if(color!=null&&trusted(web.getUrl())){accentColor=Color.parseColor(color);updateBars(web.getUrl());}return true;}
        if ("/__phone_copy__/".equals(path)) { String text=Uri.parse(url).getQueryParameter("text");if(text!=null&&text.length()<=30000){((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(android.content.ClipData.newPlainText("消息",text));toast("已复制");}return true; }
        if ("/__phone_scan__/".equals(path) || "/app/pages/".equals(path) && "scan".equals(Uri.parse(url).getQueryParameter("view"))) { startActivityForResult(new Intent(this, ScannerActivity.class), SCAN_CODE); return true; }
        if ("/__phone_update__/".equals(path)) { updater.check(true); return true; }
        if ("/__phone_connection__/".equals(path)) { showConnection(); return true; }
        if ("/__phone_background__/".equals(path)) { backgroundMessages(); return true; }
        if ("/__phone_settings__/".equals(path)) { showMenu(); return true; }
        if ("/__phone_backup__/".equals(path)) { saveChatBackup(); return true; }
        if ("/login/".equals(path)) { showLogin(); return true; }
        if ("/messages/points/".equals(path)) { navigate("/me/?mobile=points"); return true; }
        if (path != null && path.startsWith("/sampling/")) {
            toast("采集器需要电脑上的本地运行环境。"); return true;
        }
        return false;
    }
    private void openExternal(String url) {
        Uri uri = Uri.parse(url);
        if (!"https".equals(uri.getScheme()) && !"http".equals(uri.getScheme())
            && !"mailto".equals(uri.getScheme()) && !"tel".equals(uri.getScheme())) {
            toast("手机端暂不支持此操作。"); return;
        }
        new AlertDialog.Builder(this).setTitle("打开外部链接")
            .setMessage(uri.getHost() == null ? url : uri.getHost())
            .setNegativeButton("取消", null).setPositiveButton("用浏览器打开", (d, w) -> {
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
                catch (ActivityNotFoundException e) { toast("未找到可打开此链接的应用。"); }
            }).show();
    }
    private void navigate(String route) {
        final int epoch=++navigationGeneration;
        if (web.getUrl() == null || !trusted(web.getUrl())) { beginNavigation(route); return; }
        web.evaluateJavascript("Boolean(document.querySelector('[data-message-input], .conversation-composer textarea, #assistant-input')?.value.trim())", dirty -> {
            if(epoch!=navigationGeneration)return;
            if ("true".equals(dirty)) {
                new AlertDialog.Builder(this).setTitle("离开当前页面？").setMessage("有尚未发送的内容。")
                    .setNegativeButton("继续编辑", null).setPositiveButton("离开", (d, w) -> {if(epoch==navigationGeneration)beginNavigation(route);}).show();
            } else beginNavigation(route);
        });
    }
    private void beginNavigation(String route) {
        if ("/workspace/".equals(route)) {
            android.content.SharedPreferences prefs=getSharedPreferences("connection",MODE_PRIVATE);
            String account=prefs.getString("account:"+origin,"");
            String selected=prefs.getString("reading-owner:"+origin+":"+account,"");
            if(selected.matches("all|[1-9][0-9]*"))route+="?ownership="+selected;
        }
        web.stopLoading();contentReady=false;updateBars(origin+route);showLoading();web.loadUrl(origin+route);
    }
    private void switchTab(int index) {
        if (!nativeLogin && isRootPage(web.getUrl()) && currentTab == index) return;
        resetHistory = true; navigate(ROUTES[index]);
    }
    private boolean isRootPage(String address) {
        if (address == null || !trusted(address)) return false;
        Uri uri = Uri.parse(address); String path = uri.getPath();
        return "/messages/social/".equals(path) || "/assistant/".equals(path) || "/workspace/".equals(path) || "/team-square/".equals(path) || "/discover/".equals(path)
            || "/me/".equals(path) && uri.getQueryParameter("mobile") == null
            || "/messages/notices/".equals(path) || "/updates/".equals(path)
            || "/messages/teams/".equals(path) && !"settings".equals(uri.getQueryParameter("tab"));
    }
    private void updateBars(String address) {
        Uri uri = address == null ? Uri.EMPTY : Uri.parse(address);
        String path = uri.getPath(); if (path == null) path = "";
        chatPage = path.matches("/messages/(personal|groups)/[0-9]+/");
        boolean ai = path.equals("/assistant/");
        boolean auth = nativeLogin || path.equals("/login/") || path.equals("/register/") || path.startsWith("/account/register")
            || path.startsWith("/account/reset") || path.startsWith("/account/forgot");
        boolean rootPage = isRootPage(address);
        toolbar.setVisibility(nativeLogin || chatPage || ai || (path.equals("/app/pages/") || path.startsWith("/files/") || path.equals("/messages/notices/")) ? View.GONE : View.VISIBLE);
        boolean showTabs = rootPage && !keyboardOpen && !auth;
        tabs.setVisibility(showTabs ? View.VISIBLE : View.GONE); tabDivider.setVisibility(showTabs ? View.VISIBLE : View.GONE);
        int selected = path.startsWith("/discover/applications/") || path.startsWith("/discover/offers/") || path.equals("/team-square/applications/") ? 0
            : path.startsWith("/assistant/") ? 2
            : path.startsWith("/team-square/") || path.startsWith("/discover/") ? 3
            : path.startsWith("/account/") || path.startsWith("/me/") || path.startsWith("/app/devices/") ? 4
            : path.startsWith("/workspace/") || path.startsWith("/api-pool/") || path.startsWith("/teams/")
                || path.startsWith("/messages/teams/") || path.startsWith("/projects/")
                || path.startsWith("/tasks/") || path.startsWith("/documents/") || path.startsWith("/experiments/") ? 1 : 0;
        more.setText(rootPage && selected == 0 ? "＋" : "⋯");
        if (!auth) currentTab = selected;
        for (int i = 0; i < LABELS.length; i++) {
            tabLabels[i].setTextColor(i == selected ? accentColor : INK);
            icons[i].active = i == selected; icons[i].invalidate();
        }
        String heading = LABELS[selected];
        if (path.startsWith("/api-pool/")) heading = "团队 API";
        else if (path.equals("/me/") && "points".equals(uri.getQueryParameter("mobile"))) heading = "我的积分";
        else if (path.equals("/me/") && "history".equals(uri.getQueryParameter("mobile"))) heading = "本机聊天记录";
        else if (path.equals("/account/")) heading = "设置";
        else if (path.equals("/app/devices/")) heading = "登录设备";
        else if (path.equals("/me/talent/")) heading = "人才资料";
        else if (path.equals("/messages/notices/")) heading = "系统通知";
        else if (path.startsWith("/team-square/")) heading = "人才与招募";
        else if (path.contains("/members/")) heading = "团队成员";
        else if (path.contains("/review/")) heading = "加入申请";
        else if (path.contains("/recruitment/")) heading = "团队招募";
        else if (path.contains("/invites/")) heading = "团队邀请";
        else if (path.equals("/messages/teams/") && "settings".equals(uri.getQueryParameter("tab"))) heading = "团队设置";
        title.setText(auth ? "知域" : heading);
        back.setVisibility(rootPage || nativeLogin || path.equals("/login/") ? View.INVISIBLE : View.VISIBLE);
    }
    private void showLoading() {
        if (contentReady && !nativeLogin && web.getUrl()!=null && web.getUrl().equals(presentedUrl) && web.getVisibility() == View.VISIBLE && web.getWidth() > 0 && web.getHeight() > 0) {
            try {
                Bitmap image = Bitmap.createBitmap(web.getWidth(), web.getHeight(), Bitmap.Config.ARGB_8888);
                web.draw(new Canvas(image)); previousPage.setImageBitmap(image); previousPage.setVisibility(View.VISIBLE);
                overlay.setVisibility(View.GONE);
            } catch (OutOfMemoryError error) { previousPage.setVisibility(View.GONE); }
        } else {
            previousPage.setVisibility(View.GONE); overlay.removeAllViews();
            overlay.addView(new BrandLoading(), new LinearLayout.LayoutParams(dp(76), dp(76)));
            TextView caption = text("正在打开" + title.getText() + "…", 14); caption.setGravity(Gravity.CENTER);
            caption.setPadding(0, dp(24), 0, 0); overlay.addView(caption); overlay.setVisibility(View.VISIBLE);
        }
        web.setVisibility(View.INVISIBLE); loadingStrip.setVisibility(View.VISIBLE);
    }
    private void connectionError(String url, String detail) {
        pageError = true; previousPage.setVisibility(View.GONE); previousPage.setImageDrawable(null); loadingStrip.setVisibility(View.GONE); failedUrl = trusted(url) ? url : origin + ROUTES[0];
        toolbar.setVisibility(View.VISIBLE); overlay.removeAllViews();
        updateBars(failedUrl);
        if(OfflinePages.page(Uri.parse(failedUrl).getPath())) {
            TextView empty=text("此页面尚无本地缓存",20);empty.setGravity(Gravity.CENTER);overlay.addView(empty);
            TextView hint=text("联网打开一次后，离线时可从原入口查看。",14);hint.setGravity(Gravity.CENTER);overlay.addView(hint);
            overlay.setVisibility(View.VISIBLE);return;
        }
        TextView heading = text("连接暂不可用", 22); heading.setTypeface(null, Typeface.BOLD);
        heading.setGravity(Gravity.CENTER); overlay.addView(heading);
        TextView info = text(detail, 15); info.setGravity(Gravity.CENTER);
        info.setPadding(0, dp(14), 0, dp(24)); overlay.addView(info);
        overlay.addView(button("重试", v -> web.loadUrl(failedUrl)));
        TextView change = text("连接设置", 15); change.setGravity(Gravity.CENTER);
        change.setPadding(0, dp(20), 0, dp(10)); change.setTextColor(GREEN);
        change.setOnClickListener(v -> showConnection()); overlay.addView(change);
        if (!getSharedPreferences("connection", MODE_PRIVATE).getString("account:" + origin, "").isEmpty())
            overlay.addView(button("查看本机聊天记录", v -> showLocalHistory()));
        overlay.setVisibility(View.VISIBLE);
    }
    private void showLocalHistory() {
        String account = getSharedPreferences("connection", MODE_PRIVATE).getString("account:" + origin, "");
        if (!account.matches("[1-9][0-9]*")) return;
        nativeLogin = false; pageError = false; contentReady = false;
        String html = "<!doctype html><html lang=zh-CN data-account='" + account + "' data-local-history='true'>"
            + "<head><meta charset=UTF-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            + "<meta http-equiv=Content-Security-Policy content=\"default-src 'none'; script-src 'unsafe-eval' 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self'; connect-src 'none'\">"
            + "</head><body><main></main></body></html>";
        String address = origin + "/me/?mobile=history";
        web.loadDataWithBaseURL(address, html, "text/html", "UTF-8", address);
    }
    private void saveChatBackup() {
        if (backupDestination != null || !trusted(web.getUrl()) || !web.getUrl().contains("/me/?mobile=history")) return;
        backupPage = web.getUrl();
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType("application/json").putExtra(Intent.EXTRA_TITLE, "Zhiyu-chat-backup.json");
        try { startActivityForResult(intent, SAVE_CHAT); }
        catch (ActivityNotFoundException e) { toast("手机未提供文件保存器。"); }
    }
    private void readChatBackup(int attempt) {
        if (isFinishing() || isDestroyed() || !trusted(web.getUrl()) || !backupPage.equals(web.getUrl()) || attempt > 100) {
            backupDestination = null; backupText.setLength(0); toast("备份未完成，请在聊天记录页面重试。"); return;
        }
        int offset = backupText.length();
        web.evaluateJavascript("JSON.stringify((()=>{const b=window.zhiyuChatBackup;if(!b?.ready)return {wait:true};"
            + "if(b.error)return {error:b.error};return {chunk:b.text.slice(" + offset + "," + (offset + 65536) + "),end:"
            + (offset + 65536) + ">=b.text.length};})())", result -> {
            try {
                JSONObject data = new JSONObject(new org.json.JSONArray("[" + result + "]").getString(0));
                if (data.optBoolean("wait")) { web.postDelayed(() -> readChatBackup(attempt + 1), 200); return; }
                if (data.has("error")) throw new IllegalStateException();
                backupText.append(data.getString("chunk"));
                if (backupText.length() > 20 * 1024 * 1024) throw new IllegalStateException();
                if (!data.optBoolean("end")) { web.post(() -> readChatBackup(attempt)); return; }
                byte[] bytes = backupText.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > 20 * 1024 * 1024) throw new IllegalStateException();
                Uri destination = backupDestination; backupDestination = null; backupText.setLength(0);
                web.evaluateJavascript("delete window.zhiyuChatBackup", null);
                files.execute(() -> {
                    try (OutputStream output = getContentResolver().openOutputStream(destination, "w")) {
                        if (output == null) throw new java.io.IOException(); output.write(bytes);
                        runOnUiThread(() -> toast("聊天记录已备份。"));
                    } catch (Exception error) { runOnUiThread(() -> toast("备份保存失败，请重试。")); }
                });
            } catch (Exception error) { backupDestination = null; backupText.setLength(0); toast("无法备份本机记录，请重试。"); }
        });
    }
    private void showLogin() {
        if(fileDownloads!=null)fileDownloads.cancel();
        if(offlinePages!=null)offlinePages.clear(origin);
        getSharedPreferences("connection", MODE_PRIVATE).edit().remove("account:" + origin).apply();
        MessageNotifications.clearMessages(this);stopService(new Intent(this,MessageNotifications.class));icons[0].badge=0;icons[0].invalidate();
        loginGeneration++; nativeLogin = true; pageError = true; contentReady = false;
        previousPage.setVisibility(View.GONE); previousPage.setImageDrawable(null); loadingStrip.setVisibility(View.GONE);
        web.setVisibility(View.INVISIBLE); overlay.removeAllViews(); overlay.setVisibility(View.VISIBLE);
        toolbar.setVisibility(View.GONE); tabs.setVisibility(View.GONE); tabDivider.setVisibility(View.GONE);
        ScrollView scroll = new ScrollView(this); scroll.setFillViewport(true);
        LinearLayout form = vertical(); form.setGravity(Gravity.CENTER_VERTICAL); scroll.addView(form);
        overlay.addView(scroll, new LinearLayout.LayoutParams(-1, -1));
        ImageView logo = new ImageView(this); logo.setImageBitmap(brandBitmap);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(64), dp(64)); logoParams.gravity = Gravity.CENTER_HORIZONTAL;
        form.addView(logo, logoParams);
        TextView heading = text("登录知域", 26); heading.setTypeface(null, Typeface.BOLD); heading.setGravity(Gravity.CENTER);
        heading.setPadding(0, dp(12), 0, dp(8)); form.addView(heading);
        TextView intro = text("消息、AI 与团队协作", 14); intro.setGravity(Gravity.CENTER); intro.setTextColor(Color.GRAY);
        intro.setPadding(0, 0, 0, dp(32)); form.addView(intro);
        TextView accountLabel = text("账号", 14); form.addView(accountLabel);
        EditText account = new EditText(this); account.setHint("工作台号或邮箱"); account.setSingleLine(true);
        account.setTextSize(16); account.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
        account.setAutofillHints(View.AUTOFILL_HINT_USERNAME); form.addView(account, new LinearLayout.LayoutParams(-1, dp(52)));
        TextView passwordLabel = text("密码", 14); passwordLabel.setPadding(0, dp(16), 0, 0); form.addView(passwordLabel);
        EditText password = new EditText(this); password.setHint("请输入密码"); password.setSingleLine(true); password.setTextSize(16);
        password.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setAutofillHints(View.AUTOFILL_HINT_PASSWORD); password.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_DONE);
        form.addView(password, new LinearLayout.LayoutParams(-1, dp(52)));
        TextView status = text("", 14); status.setTextColor(Color.rgb(165, 44, 44)); status.setPadding(0, dp(12), 0, dp(12));
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE); form.addView(status);
        TextView submit = button("登录", null); form.addView(submit, new LinearLayout.LayoutParams(-1, dp(48)));
        Runnable login = () -> {
            if (!submit.isEnabled()) return;
            String username = account.getText().toString().trim(), secret = password.getText().toString();
            if (username.isEmpty() || secret.isEmpty()) { status.setText("请输入账号和密码。"); return; }
            final String server = origin; final int generation = loginGeneration;
            submit.setEnabled(false); submit.setText("正在登录…"); status.setText(""); loadingStrip.setVisibility(View.VISIBLE);
            files.execute(() -> {
                String failure = ""; boolean success = false;
                try {
                    HttpURLConnection bootstrap = authConnection(server, "/login/");
                    try { if (bootstrap.getResponseCode() >= 400) throw new java.io.IOException(); storeCookies(server, bootstrap); }
                    finally { bootstrap.disconnect(); }
                    String cookies = CookieManager.getInstance().getCookie(server + "/login/");
                    Matcher match = Pattern.compile("(?:^|;\\s*)csrftoken=([^;]+)").matcher(cookies == null ? "" : cookies);
                    if (!match.find()) throw new java.io.IOException();
                    String data = "username=" + URLEncoder.encode(username, "UTF-8") + "&password=" + URLEncoder.encode(secret, "UTF-8")
                        + "&csrfmiddlewaretoken=" + URLEncoder.encode(match.group(1), "UTF-8") + "&remember=on&next=%2Fmessages%2Fsocial%2F";
                    HttpURLConnection request = authConnection(server, "/login/");
                    try {
                        request.setRequestMethod("POST"); request.setDoOutput(true);
                        request.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
                        request.setRequestProperty("Origin", server); request.setRequestProperty("Referer", server + "/login/");
                        byte[] body = data.getBytes(StandardCharsets.UTF_8); request.setFixedLengthStreamingMode(body.length);
                        try (OutputStream output = request.getOutputStream()) { output.write(body); }
                        int code = request.getResponseCode(); storeCookies(server, request);
                        String destination = request.getHeaderField("Location");
                        success = code >= 300 && code < 400 && destination != null
                            && trusted(new URL(new URL(server + "/login/"), destination).toString())
                            && !new URL(new URL(server + "/login/"), destination).getPath().equals("/login/");
                        if (!success) failure = code >= 500 ? "服务器暂时不可用，请稍后重试。" : code == 403 ? "登录验证已过期，请重试。" : code == 429 ? "尝试过于频繁，请稍后重试。" : "账号或密码不正确，或账号已停用。";
                    } finally { request.disconnect(); }
                } catch (Exception error) { failure = "暂时连接不上服务器，请检查网络后重试。"; }
                final boolean authenticated = success; final String message = failure;
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed() || generation != loginGeneration || !server.equals(origin)) return;
                    loadingStrip.setVisibility(View.GONE); submit.setEnabled(true); submit.setText("登录");
                    if (authenticated) {
                        password.setText(""); CookieManager.getInstance().flush(); nativeLogin = false; pageError = false; resetHistory = true;
                        android.view.inputmethod.InputMethodManager input = (android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
                        if (input != null) input.hideSoftInputFromWindow(password.getWindowToken(), 0);
                        web.loadUrl(origin + ROUTES[0]);
                    } else status.setText(message);
                });
            });
        };
        submit.setOnClickListener(v -> login.run());
        password.setOnEditorActionListener((v, action, event) -> { if (action == android.view.inputmethod.EditorInfo.IME_ACTION_DONE) { login.run(); return true; } return false; });
        TextView forgot = text("忘记密码", 14); forgot.setGravity(Gravity.CENTER); forgot.setTextColor(GREEN); forgot.setPadding(0, dp(18), 0, dp(8));
        forgot.setOnClickListener(v -> { nativeLogin = false; pageError = false; navigate("/account/forgot/"); }); form.addView(forgot);
        TextView register = text("创建账号", 14); register.setGravity(Gravity.CENTER); register.setMinHeight(dp(44)); register.setTextColor(GREEN);
        register.setOnClickListener(v -> { nativeLogin = false; pageError = false; navigate("/account/register/"); }); form.addView(register);
        TextView connection = text("连接设置", 14); connection.setGravity(Gravity.CENTER); connection.setMinHeight(dp(44)); connection.setTextColor(Color.GRAY);
        connection.setOnClickListener(v -> showConnection()); form.addView(connection);
    }
    private HttpURLConnection authConnection(String server, String path) throws Exception {
        HttpURLConnection request = (HttpURLConnection) new URL(server + path).openConnection();
        request.setConnectTimeout(15000); request.setReadTimeout(20000); request.setInstanceFollowRedirects(false);
        request.setRequestProperty("User-Agent", "ZhiyuMobile/" + BuildConfig.VERSION_NAME);
        String cookie = CookieManager.getInstance().getCookie(server + path);
        if (cookie != null) request.setRequestProperty("Cookie", cookie);
        return request;
    }
    private void storeCookies(String server, HttpURLConnection request) {
        for (java.util.Map.Entry<String, java.util.List<String>> entry : request.getHeaderFields().entrySet())
            if ("Set-Cookie".equalsIgnoreCase(entry.getKey()))
                for (String cookie : entry.getValue()) CookieManager.getInstance().setCookie(server + "/login/", cookie);
    }
    void updateAvailable(boolean value){runOnUiThread(()->{icons[4].badge=value?-1:0;icons[4].invalidate();});}
    private final Runnable badgeRefresh=new Runnable(){public void run(){
        if(isFinishing()||isDestroyed())return;
        if(!nativeLogin&&MessageNotifications.foreground&&trusted(web.getUrl()))web.evaluateJavascript("Number(window.zhiyuNotificationSnapshot?.total)||0",value->{try{int count=Integer.parseInt(value);icons[0].badge=Math.max(0,count);icons[0].invalidate();}catch(Exception ignored){}});
        web.postDelayed(this,8000);
    }};
    private void startMessageSync(){
        if(!getSharedPreferences("connection",MODE_PRIVATE).getBoolean("background-messages",false)||nativeLogin)return;
        if(android.os.Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)return;
        try{startForegroundService(new Intent(this,MessageNotifications.class));}catch(Exception e){toast("系统暂未允许后台消息同步，请重新打开应用后再试。");}
    }
    private void backgroundMessages(){
        boolean enabled=getSharedPreferences("connection",MODE_PRIVATE).getBoolean("background-messages",false);
        new AlertDialog.Builder(this).setTitle("后台消息提醒").setMessage("开启后会显示后台同步通知，收到消息时可提示。系统省电和后台运行限制可能中止同步；重新打开应用会恢复。")
            .setNegativeButton("取消",null).setPositiveButton(enabled?"关闭提醒":"开启提醒",(d,w)->{
                getSharedPreferences("connection",MODE_PRIVATE).edit().putBoolean("background-messages",!enabled).apply();
                if(enabled){MessageNotifications.clearMessages(this);stopService(new Intent(this,MessageNotifications.class));toast("已关闭后台提醒");}
                else if(android.os.Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS},16);
                else startMessageSync();
            }).show();
    }
    private void openNotification(Intent intent){
        if(intent==null||!origin.equals(intent.getStringExtra("message-origin")))return;
        String account=getSharedPreferences("connection",MODE_PRIVATE).getString("account:"+origin,"");
        if(!account.equals(intent.getStringExtra("message-account")))return;
        String path=intent.getStringExtra("message-path");
        if(path!=null&&path.matches("/messages/(personal|groups)/[1-9][0-9]*/")){intent.removeExtra("message-path");web.loadUrl(origin+path);}
    }
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);openNotification(intent);}
    private void showMenu() {
        new AlertDialog.Builder(this).setTitle("知域 · 手机版")
            .setItems(new String[]{"刷新当前页面", "检查手机版更新", "连接设置", "后台消息提醒", "关于手机版"}, (d, index) -> {
                if (index == 0) { offlinePages.force(); web.reload(); }
                else if (index == 1) updater.check(true);
                else if (index == 2) showConnection();
                else if(index == 3)backgroundMessages();
                else new AlertDialog.Builder(this).setTitle("知域 " + BuildConfig.VERSION_NAME)
                    .setMessage("消息、AI 助手与团队 API 随身使用。\n\n连接现有团队服务器；账号与权限沿用电脑版。\n\n可在设置中开启后台消息提醒；系统省电限制可能暂停同步。")
                    .setNeutralButton("检查更新", (about, button) -> updater.check(true)).setPositiveButton("知道了", null).show();
            }).show();
    }
    private void showConnection() {
        EditText input = new EditText(this); input.setText(origin); input.setSingleLine(true);
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_VARIATION_URI);
        input.setPadding(dp(20), dp(12), dp(20), dp(12));
        AlertDialog dialog = new AlertDialog.Builder(this).setTitle("团队服务器")
            .setMessage("填写完整地址，例如 " + DEFAULT_SERVER + "。更换后需在新服务器登录。")
            .setView(input).setNegativeButton("取消", null).setPositiveButton("保存", null).create();
        dialog.setOnShowListener(d -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            final String next;
            try { next = normalizeOrigin(input.getText().toString()); }
            catch (Exception e) { input.setError("请输入有效的 HTTP 或 HTTPS 服务器地址，不含路径。"); return; }
            if (next.equals(origin)) { dialog.dismiss(); return; }
            loginGeneration++; nativeLogin = false; contentReady = false;
            MessageNotifications.clearMessages(this);stopService(new Intent(this,MessageNotifications.class));web.stopLoading(); origin = next;
            getSharedPreferences("connection", MODE_PRIVATE).edit().putString("origin", origin).apply();
            web.clearHistory(); dialog.dismiss(); web.loadUrl(origin + ROUTES[0]);
        }));
        dialog.show();
    }
    private void goUp() {
        String path = web.getUrl() == null ? "" : Uri.parse(web.getUrl()).getPath();
        if (path != null && (path.startsWith("/account/forgot") || path.startsWith("/account/register") || path.startsWith("/account/reset"))) { showLogin(); return; }
        if (isRootPage(web.getUrl())) { moveTaskToBack(true); return; }
        if (web.canGoBack()) web.goBack(); else navigate(ROUTES[currentTab]);
    }
    private void handleBack() {
        if (nativeLogin) { moveTaskToBack(true); return; }
        if (keyboardOpen) {
            android.view.inputmethod.InputMethodManager input =
                (android.view.inputmethod.InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (input != null) input.hideSoftInputFromWindow(web.getWindowToken(), 0);
            return;
        }
        if (trusted(web.getUrl())) {
            web.evaluateJavascript("(function(){var c=document.querySelector('.chat-sticker-popover');if(c){c.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));return true;}var ds=document.querySelectorAll('dialog[open]'),d=ds[ds.length-1];"
                + "if(d){if(d.dataset.busy==='true')return true;var e=new Event('cancel',{cancelable:true});if(d.dispatchEvent(e))d.close();return true;}c=document.querySelector('.experience-add-menu,.experience-contact-card');if(c){c.remove();return true;}var p=document.querySelector('[data-chat-details]:not([hidden])');"
                + "if(p){document.querySelector('[data-chat-details-close]')?.click();return true;}"
                + "var a=document.querySelector('#assistant-app:not(.sidebar-collapsed)');"
                + "if(a){document.querySelector('#assistant-sidebar-close')?.click();return true;}return false;})()", handled -> {
                    if (!"true".equals(handled)) goUp();
                });
        } else if (web.canGoBack()) web.goBack(); else moveTaskToBack(true);
    }
    @Override @SuppressWarnings("deprecation") public void onBackPressed() { handleBack(); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == MobileUpdater.INSTALL_PERMISSION) {
            if (getPackageManager().canRequestPackageInstalls()) updater.installReady();
            return;
        }
        if(request == SCAN_CODE && result == RESULT_OK && data != null && trusted(web.getUrl())) {
            String route=data.getStringExtra("route");if("/app/pages/?view=my-qr".equals(route)){navigate(route);return;}
            String value=data.getStringExtra("code"); if(value != null) web.evaluateJavascript("window.zhiyuExperience?.scanResult("+JSONObject.quote(value)+")",null); return;
        }
        if(request == TAKE_PHOTO) {
            if(filePicker != null) { filePicker.onReceiveValue(result == RESULT_OK && cameraOutput != null ? new Uri[]{cameraOutput} : null); filePicker=null; }
            if(cameraOutput != null) revokeUriPermission(cameraOutput,Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            cameraOutput=null; return;
        }
        if (request == PICK_FILES && filePicker != null) {
            filePicker.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data)); filePicker = null;
        } else if (request == SAVE_CHAT && result == RESULT_OK && data != null && data.getData() != null) {
            if (backupPage == null || !backupPage.equals(web.getUrl()) || !trusted(backupPage)) return;
            backupDestination = data.getData(); backupText.setLength(0);
            web.evaluateJavascript("window.zhiyuPrepareChatBackup?.();", ignored -> readChatBackup(0));
        } else if (request == SAVE_FILE && result == RESULT_OK && data != null && data.getData() != null) {
            Uri destination = data.getData(); String url = pendingDownload, cookie = pendingCookie;
            toast("正在保存附件…");
            files.execute(() -> saveDownload(url, cookie, destination));
        }
    }
    private void saveDownload(String url, String cookie, Uri destination) {
        HttpURLConnection connection = null;
        try {
            for (int redirects = 0; redirects < 5; redirects++) {
                if (!trusted(url)) throw new IllegalStateException("下载跳转到外部服务器");
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setConnectTimeout(20000); connection.setReadTimeout(60000);
                connection.setInstanceFollowRedirects(false);
                if (cookie != null) connection.setRequestProperty("Cookie", cookie);
                int code = connection.getResponseCode();
                if (code >= 300 && code < 400) {
                    String next = connection.getHeaderField("Location");
                    if (next == null) throw new IllegalStateException("无效的下载跳转");
                    url = new URL(new URL(url), next).toString(); connection.disconnect(); connection = null; continue;
                }
                String contentType = connection.getContentType();
                if (code != 200 || (contentType != null && "text/html".equalsIgnoreCase(contentType.split(";", 2)[0])))
                    throw new IllegalStateException("请重新登录后下载");
                try (InputStream in = connection.getInputStream(); OutputStream out = getContentResolver().openOutputStream(destination, "w")) {
                    if (out == null) throw new IllegalStateException("无法写入所选位置");
                    byte[] bytes = new byte[32768]; int count;
                    while ((count = in.read(bytes)) >= 0) out.write(bytes, 0, count);
                }
                runOnUiThread(() -> toast("附件已保存。")); return;
            }
            throw new IllegalStateException("下载重定向过多");
        } catch (Exception e) { runOnUiThread(() -> toast("附件保存失败，请重试。")); }
        finally { if (connection != null) connection.disconnect(); }
    }
    private String readAsset(String name) throws Exception {
        try (InputStream input = getAssets().open(name); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] bytes = new byte[8192]; int count;
            while ((count = input.read(bytes)) != -1) output.write(bytes, 0, count);
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }
    private void toast(String value) { Toast.makeText(this, value, Toast.LENGTH_LONG).show(); }
    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); web.saveState(state); }
    @Override protected void onResume() { super.onResume();MessageNotifications.foreground=true;startMessageSync(); if (web != null) { web.onResume(); web.resumeTimers(); } }
    @Override protected void onPause() {MessageNotifications.foreground=false; if (web != null) { CookieManager.getInstance().flush(); web.onPause(); web.pauseTimers(); } super.onPause(); }
    @Override protected void onDestroy() {
        if (filePicker != null) filePicker.onReceiveValue(null);
        if (web != null) { ((FrameLayout) web.getParent()).removeView(web); web.destroy(); }
        if (updater != null) updater.close();
        if (offlinePages != null) offlinePages.close();
        if(fileDownloads!=null)fileDownloads.close();
        files.shutdown(); super.onDestroy();
    }

    /** Same brand mask and two flowing paths as desktop/ui/loading.css. */
    private final class BrandLoading extends View {
        private final Paint pen = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Bitmap brand = brandBitmap;
        private final Path first = new Path(), second = new Path();
        BrandLoading() {
            super(MainActivity.this); setContentDescription("知域正在加载");
            first.moveTo(372,482); first.lineTo(336,432); first.quadTo(307,400,343,368); first.lineTo(402,320);
            first.quadTo(426,301,454,323); first.lineTo(756,563); first.lineTo(925,758); first.quadTo(955,805,916,853);
            first.lineTo(852,912); first.quadTo(833,929,810,911); first.lineTo(484,675);
            second.moveTo(556,529); second.lineTo(373,690); second.quadTo(312,750,327,825); second.quadTo(341,926,403,904);
            second.lineTo(559,817); second.lineTo(843,598); second.quadTo(916,528,927,443); second.quadTo(941,365,884,340);
            second.quadTo(864,329,839,348); second.lineTo(688,444);
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); if (brand == null) return;
            float cycle = (SystemClock.uptimeMillis()%2800)/2800f;
            float breath = .97f + .03f * (float)(1-Math.cos(cycle*2*Math.PI))/2;
            canvas.save(); canvas.scale(getWidth()/750f*breath, getHeight()/710f*breath); canvas.translate(-250,-270);
            int layer = canvas.saveLayer(250,270,1000,980,null);
            pen.setColorFilter(new ColorMatrixColorFilter(new ColorMatrix(new float[]{0,0,0,0,100,0,0,0,0,100,0,0,0,0,100,-1,-1,-1,0,561})));
            pen.setStyle(Paint.Style.FILL); canvas.drawBitmap(brand,null,new android.graphics.RectF(0,0,1254,1254),pen);
            pen.setColorFilter(null); pen.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.SRC_ATOP));
            pen.setColor(INK); pen.setStyle(Paint.Style.STROKE); pen.setStrokeWidth(78); pen.setStrokeCap(Paint.Cap.ROUND);
            float phase = (SystemClock.uptimeMillis()%3000)/3000f*2530;
            pen.setPathEffect(new DashPathEffect(new float[]{130,2400},phase)); canvas.drawPath(first,pen);
            pen.setPathEffect(new DashPathEffect(new float[]{130,2400},phase+1265)); canvas.drawPath(second,pen);
            pen.setXfermode(null); pen.setPathEffect(null); canvas.restoreToCount(layer); canvas.restore();
            if (isShown()) postInvalidateOnAnimation();
        }
    }
    private final class LoadingStrip extends View {
        private final Paint pen = new Paint();
        LoadingStrip() { super(MainActivity.this); setContentDescription("正在加载"); }
        @Override protected void onDraw(Canvas canvas) {
            pen.setColor(Color.rgb(229,233,231)); canvas.drawRect(0,0,getWidth(),getHeight(),pen);
            float progress = (SystemClock.uptimeMillis()%1300)/1300f;
            float start = getWidth()*(-.3f+1.6f*(.5f-.5f*(float)Math.cos(progress*Math.PI)));
            pen.setColor(INK); canvas.drawRect(start,0,start+getWidth()*.3f,getHeight(),pen);
            if (isShown()) postInvalidateOnAnimation();
        }
    }

    private final class TabIcon extends View {
        private final Paint pen = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int kind;
        boolean active;int badge;
        TabIcon(int kind) { super(MainActivity.this); this.kind = kind; }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); canvas.save(); canvas.scale(getWidth()/24f, getHeight()/24f);
            pen.setColor(active ? accentColor : INK); pen.setStrokeWidth(1.7f);
            pen.setStyle(Paint.Style.STROKE); pen.setStrokeJoin(Paint.Join.ROUND); pen.setStrokeCap(Paint.Cap.ROUND);
            if (kind == 0) {
                canvas.drawRoundRect(3, 3, 21, 18, 5, 5, pen);
                Path tail = new Path(); tail.moveTo(5, 18); tail.lineTo(4, 21); tail.lineTo(10, 18); canvas.drawPath(tail, pen);
                canvas.drawLine(7, 8, 17, 8, pen); canvas.drawLine(7, 12, 14, 12, pen);
            } else if (kind == 2) {
                Path star = new Path(); star.moveTo(12, 2); star.lineTo(15, 9); star.lineTo(22, 12);
                star.lineTo(15, 15); star.lineTo(12, 22); star.lineTo(9, 15); star.lineTo(2, 12); star.lineTo(9, 9); star.close(); canvas.drawPath(star, pen);
            } else if (kind == 1) {
                canvas.drawRoundRect(3, 3, 10, 10, 1, 1, pen); canvas.drawRoundRect(14, 3, 21, 10, 1, 1, pen);
                canvas.drawRoundRect(3, 14, 10, 21, 1, 1, pen); canvas.drawRoundRect(14, 14, 21, 21, 1, 1, pen);
            } else if (kind == 3) {
                canvas.drawCircle(12, 12, 10, pen); Path compass = new Path(); compass.moveTo(16, 7); compass.lineTo(14, 14); compass.lineTo(7, 17); compass.lineTo(10, 10); compass.close(); canvas.drawPath(compass, pen);
            } else if (kind == 9) {
                canvas.drawCircle(8, 7, 3, pen); canvas.drawCircle(17, 8, 2.5f, pen);
                canvas.drawArc(2, 13, 14, 26, 180, 180, false, pen); canvas.drawArc(13, 14, 22, 24, 180, 180, false, pen);
            } else {
                canvas.drawCircle(12, 7, 4, pen); canvas.drawArc(4, 14, 20, 30, 180, 180, false, pen);
            }
            if(badge!=0){pen.setStyle(Paint.Style.FILL);pen.setColor(Color.rgb(231,69,75));canvas.drawCircle(19,5,badge<0?3:5,pen);pen.setColor(Color.WHITE);pen.setTextSize(badge>9?6:8);pen.setTextAlign(Paint.Align.CENTER);if(badge>0)canvas.drawText(badge>99?"99+":String.valueOf(badge),19,8,pen);}
            canvas.restore();
        }
    }
}
