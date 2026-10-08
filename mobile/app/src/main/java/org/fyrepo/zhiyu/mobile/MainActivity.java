package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Canvas;
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
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** A small phone shell. Sessions and all permissions stay with the existing server. */
public final class MainActivity extends Activity {
    private static final int GREEN = Color.rgb(7, 160, 90);
    private static final int INK = Color.rgb(31, 35, 40);
    private static final int PAPER = Color.rgb(247, 248, 250);
    private static final int PICK_FILES = 10, SAVE_FILE = 11;
    private static final String DEFAULT_SERVER = "http://47.117.89.248";
    private static final String[] LABELS = {"消息", "AI", "团队", "我"};
    private static final String[] ROUTES = {"/messages/social/", "/assistant/", "/messages/teams/", "/me/"};
    private WebView web;
    private LinearLayout root, toolbar, tabs, overlay;
    private TextView title, back;
    private final TextView[] tabLabels = new TextView[4];
    private final TabIcon[] icons = new TabIcon[4];
    private ValueCallback<Uri[]> filePicker;
    private String origin, css, script, failedUrl, pendingDownload, pendingCookie;
    private boolean keyboardOpen, chatPage, pageError;
    private final ExecutorService files = Executors.newSingleThreadExecutor();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        SharedPreferences settings = getSharedPreferences("connection", MODE_PRIVATE);
        origin = settings.getString("origin", DEFAULT_SERVER);
        try { origin = normalizeOrigin(origin); }
        catch (Exception ignored) { origin = DEFAULT_SERVER; }
        try {
            css = readAsset("mobile.css");
            script = readAsset("mobile.js");
        } catch (Exception e) { throw new IllegalStateException("Missing mobile interface", e); }
        createLayout();
        setupBrowser();
        if (state == null || web.restoreState(state) == null) web.loadUrl(origin + ROUTES[0]);
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
        TextView more = text("⋯", 28); more.setGravity(Gravity.CENTER);
        more.setContentDescription("连接与应用设置"); more.setOnClickListener(v -> showMenu());
        toolbar.addView(more, new LinearLayout.LayoutParams(dp(44), dp(50)));
        root.addView(toolbar);
        FrameLayout stage = new FrameLayout(this);
        root.addView(stage, new LinearLayout.LayoutParams(-1, 0, 1));
        web = new WebView(this); web.setBackgroundColor(Color.WHITE);
        stage.addView(web, new FrameLayout.LayoutParams(-1, -1));
        overlay = vertical(); overlay.setGravity(Gravity.CENTER); overlay.setBackgroundColor(PAPER);
        overlay.setPadding(dp(32), dp(20), dp(32), dp(20));
        stage.addView(overlay, new FrameLayout.LayoutParams(-1, -1));
        tabs = new LinearLayout(this); tabs.setBackgroundColor(PAPER);
        tabs.setPadding(0, dp(4), 0, dp(3));
        for (int i = 0; i < 4; i++) {
            final int index = i;
            LinearLayout cell = vertical(); cell.setGravity(Gravity.CENTER);
            cell.setContentDescription(LABELS[i]); cell.setOnClickListener(v -> navigate(ROUTES[index]));
            icons[i] = new TabIcon(i); cell.addView(icons[i], new LinearLayout.LayoutParams(dp(28), dp(28)));
            tabLabels[i] = text(LABELS[i], 11); tabLabels[i].setGravity(Gravity.CENTER);
            cell.addView(tabLabels[i], new LinearLayout.LayoutParams(-1, dp(20)));
            tabs.addView(cell, new LinearLayout.LayoutParams(0, dp(54), 1));
        }
        View divider = new View(this); divider.setBackgroundColor(Color.rgb(230, 233, 235));
        root.addView(divider, new LinearLayout.LayoutParams(-1, dp(1)));
        root.addView(tabs);
        setContentView(root);
        root.getViewTreeObserver().addOnGlobalLayoutListener(() -> {
            Rect visible = new Rect(); root.getWindowVisibleDisplayFrame(visible);
            boolean open = root.getRootView().getHeight() - visible.bottom > dp(180);
            if (open != keyboardOpen) { keyboardOpen = open; updateBars(web.getUrl()); }
        });
        showLoading();
    }

    @SuppressWarnings("deprecation") private void setupBrowser() {
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
        settings.setUserAgentString(settings.getUserAgentString() + " ZhiyuMobile/0.4.4-mobile.1");
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        // No JavaScript-to-Java bridge is exposed to server content.
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (!request.isForMainFrame()) return false;
                return handleNavigation(request.getUrl().toString());
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                pageError = false; updateBars(url); showLoading();
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!trusted(url) || pageError) return;
                String injection = "(function(){var s=document.getElementById('zhiyu-phone-css');"
                    + "if(!s){s=document.createElement('style');s.id='zhiyu-phone-css';document.head.append(s);}"
                    + "s.textContent=" + JSONObject.quote(css) + ";" + script + "})()";
                view.evaluateJavascript(injection, result -> {
                    if (!pageError) { overlay.setVisibility(View.GONE); web.setVisibility(View.VISIBLE); }
                });
                CookieManager.getInstance().flush();
                updateBars(url);
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) connectionError(request.getUrl().toString(), "暂时连接不上团队服务器。");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500)
                    connectionError(request.getUrl().toString(), "服务器暂时不可用（" + response.getStatusCode() + "）。");
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel();
                connectionError(view.getUrl(), "服务器 HTTPS 证书无效，请检查连接地址。");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (!trusted(view.getUrl())) { callback.onReceiveValue(null); return true; }
                if (filePicker != null) filePicker.onReceiveValue(null);
                filePicker = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                intent.setType("*/*");
                String[] accepted = params.getAcceptTypes();
                if (accepted.length > 0 && !accepted[0].isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, accepted);
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(intent, PICK_FILES); }
                catch (ActivityNotFoundException e) { filePicker.onReceiveValue(null); filePicker = null; toast("手机未提供文件选择器。"); }
                return true;
            }
        });
        web.setDownloadListener((url, agent, disposition, mime, length) -> {
            if (!trusted(url)) { openExternal(url); return; }
            pendingDownload = url; pendingCookie = CookieManager.getInstance().getCookie(url);
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType(mime == null ? "application/octet-stream" : mime);
            String name = URLUtil.guessFileName(url, disposition, mime).replaceAll("[\\\\/:*?\"<>|]", "_");
            intent.putExtra(Intent.EXTRA_TITLE, name);
            try { startActivityForResult(intent, SAVE_FILE); }
            catch (ActivityNotFoundException e) { toast("手机未提供文件保存器。"); }
            overlay.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
        });
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
        if (path != null && (path.startsWith("/sampling/") || path.startsWith("/api-pool/manage/")
            || path.startsWith("/platform/") || path.contains("/office/") || path.startsWith("/assistant/web-preview/")
            || path.matches("/(projects|experiments|documents)/new/.*")
            || path.matches("/(projects|experiments|documents)/[0-9]+/edit/.*"))) {
            toast("这项复杂操作请在电脑版完成。"); return true;
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
        if (web.getUrl() == null || !trusted(web.getUrl())) { web.loadUrl(origin + route); return; }
        web.evaluateJavascript("Boolean(document.querySelector('textarea')?.value.trim())", dirty -> {
            if ("true".equals(dirty)) {
                new AlertDialog.Builder(this).setTitle("离开当前页面？").setMessage("有尚未发送的内容。")
                    .setNegativeButton("继续编辑", null).setPositiveButton("离开", (d, w) -> web.loadUrl(origin + route)).show();
            } else web.loadUrl(origin + route);
        });
    }
    private void updateBars(String address) {
        String path = address == null ? "" : Uri.parse(address).getPath();
        if (path == null) path = "";
        chatPage = path.matches("/messages/(personal|groups)/[0-9]+/");
        boolean ai = path.equals("/assistant/");
        toolbar.setVisibility(chatPage || ai ? View.GONE : View.VISIBLE);
        boolean auth = path.equals("/login/") || path.equals("/register/") || path.startsWith("/account/register")
            || path.startsWith("/account/reset") || path.startsWith("/account/forgot");
        tabs.setVisibility(chatPage || keyboardOpen || auth ? View.GONE : View.VISIBLE);
        int selected = path.startsWith("/assistant/") ? 1 : path.startsWith("/api-pool/")
            || path.startsWith("/messages/teams/") || path.startsWith("/teams/")
            || path.startsWith("/team-square/") || path.startsWith("/discover/") ? 2
            : path.startsWith("/account/") || path.startsWith("/me/") ? 3 : 0;
        for (int i = 0; i < 4; i++) {
            tabLabels[i].setTextColor(i == selected ? GREEN : INK);
            icons[i].active = i == selected; icons[i].invalidate();
        }
        title.setText(auth ? "知域" : path.startsWith("/api-pool/") ? "团队 API" : LABELS[selected]);
        back.setVisibility(web.canGoBack() ? View.VISIBLE : View.INVISIBLE);
    }
    private void showLoading() {
        web.setVisibility(View.INVISIBLE); overlay.removeAllViews();
        overlay.addView(new ProgressBar(this), new LinearLayout.LayoutParams(dp(32), dp(32)));
        TextView caption = text("正在连接…", 14); caption.setGravity(Gravity.CENTER);
        caption.setPadding(0, dp(16), 0, 0); overlay.addView(caption);
        overlay.setVisibility(View.VISIBLE);
    }
    private void connectionError(String url, String detail) {
        pageError = true; failedUrl = trusted(url) ? url : origin + ROUTES[0];
        toolbar.setVisibility(View.VISIBLE); overlay.removeAllViews();
        TextView heading = text("连接暂不可用", 22); heading.setTypeface(null, Typeface.BOLD);
        heading.setGravity(Gravity.CENTER); overlay.addView(heading);
        TextView info = text(detail, 15); info.setGravity(Gravity.CENTER);
        info.setPadding(0, dp(14), 0, dp(24)); overlay.addView(info);
        overlay.addView(button("重试", v -> web.loadUrl(failedUrl)));
        TextView change = text("连接设置", 15); change.setGravity(Gravity.CENTER);
        change.setPadding(0, dp(20), 0, dp(10)); change.setTextColor(GREEN);
        change.setOnClickListener(v -> showConnection()); overlay.addView(change);
        overlay.setVisibility(View.VISIBLE);
    }
    private void showMenu() {
        new AlertDialog.Builder(this).setTitle("知域 · 手机版")
            .setItems(new String[]{"刷新当前页面", "连接设置", "关于手机版"}, (d, index) -> {
                if (index == 0) web.reload();
                else if (index == 1) showConnection();
                else new AlertDialog.Builder(this).setTitle("知域 " + BuildConfig.VERSION_NAME)
                    .setMessage("消息、AI 助手与团队 API 随身使用。\n\n连接现有团队服务器；账号与权限沿用电脑版。\n\n后台退出后不会接收实时推送，重新打开会同步消息。")
                    .setPositiveButton("知道了", null).show();
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
            web.stopLoading(); origin = next;
            getSharedPreferences("connection", MODE_PRIVATE).edit().putString("origin", origin).apply();
            web.clearHistory(); dialog.dismiss(); web.loadUrl(origin + ROUTES[0]);
        }));
        dialog.show();
    }
    private void handleBack() {
        if (trusted(web.getUrl())) {
            web.evaluateJavascript("(function(){var d=document.querySelector('dialog[open]');"
                + "if(d){d.close();return true;}var p=document.querySelector('[data-chat-details]:not([hidden])');"
                + "if(p){document.querySelector('[data-chat-details-close]')?.click();return true;}"
                + "var a=document.querySelector('#assistant-app:not(.sidebar-collapsed)');"
                + "if(a){document.querySelector('#assistant-sidebar-close')?.click();return true;}return false;})()", handled -> {
                    if (!"true".equals(handled)) { if (web.canGoBack()) web.goBack(); else moveTaskToBack(true); }
                });
        } else if (web.canGoBack()) web.goBack(); else moveTaskToBack(true);
    }
    @Override @SuppressWarnings("deprecation") public void onBackPressed() { handleBack(); }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILES && filePicker != null) {
            filePicker.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data)); filePicker = null;
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
    @Override protected void onResume() { super.onResume(); if (web != null) { web.onResume(); web.resumeTimers(); } }
    @Override protected void onPause() { if (web != null) { CookieManager.getInstance().flush(); web.onPause(); web.pauseTimers(); } super.onPause(); }
    @Override protected void onDestroy() {
        if (filePicker != null) filePicker.onReceiveValue(null);
        if (web != null) { ((FrameLayout) web.getParent()).removeView(web); web.destroy(); }
        files.shutdown(); super.onDestroy();
    }

    private final class TabIcon extends View {
        private final Paint pen = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int kind;
        boolean active;
        TabIcon(int kind) { super(MainActivity.this); this.kind = kind; }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas); canvas.save(); canvas.scale(getWidth()/24f, getHeight()/24f);
            pen.setColor(active ? GREEN : INK); pen.setStrokeWidth(1.7f);
            pen.setStyle(Paint.Style.STROKE); pen.setStrokeJoin(Paint.Join.ROUND); pen.setStrokeCap(Paint.Cap.ROUND);
            if (kind == 0) {
                canvas.drawRoundRect(3, 3, 21, 18, 5, 5, pen);
                Path tail = new Path(); tail.moveTo(5, 18); tail.lineTo(4, 21); tail.lineTo(10, 18); canvas.drawPath(tail, pen);
                canvas.drawLine(7, 8, 17, 8, pen); canvas.drawLine(7, 12, 14, 12, pen);
            } else if (kind == 1) {
                Path star = new Path(); star.moveTo(12, 2); star.lineTo(15, 9); star.lineTo(22, 12);
                star.lineTo(15, 15); star.lineTo(12, 22); star.lineTo(9, 15); star.lineTo(2, 12); star.lineTo(9, 9); star.close(); canvas.drawPath(star, pen);
            } else if (kind == 2) {
                canvas.drawCircle(8, 7, 3, pen); canvas.drawCircle(17, 8, 2.5f, pen);
                canvas.drawArc(2, 13, 14, 26, 180, 180, false, pen); canvas.drawArc(13, 14, 22, 24, 180, 180, false, pen);
            } else {
                canvas.drawCircle(12, 7, 4, pen); canvas.drawArc(4, 14, 20, 30, 180, 180, false, pen);
            }
            canvas.restore();
        }
    }
}
