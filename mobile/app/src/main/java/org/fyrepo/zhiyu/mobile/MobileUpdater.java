package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Base64;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Independent Android channel: never consume desktop version numbers or cookies. */
final class MobileUpdater {
    static final int INSTALL_PERMISSION = 12;
    private static final String FEED = "https://api.github.com/repos/L1nYux/FYrepo/contents/mobile/update-channel.json?ref=android-stable";
    private static final String CERTIFICATE = "3e75df8797636280a339976c306de74425c9bdc24abda48d8cb49f9e7fe8a195";
    private final Activity activity;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicBoolean checking = new AtomicBoolean(), downloading = new AtomicBoolean();
    private volatile boolean cancelled;
    private volatile HttpURLConnection currentDownload;
    private JSONObject ready;
    private AlertDialog progress;

    MobileUpdater(Activity activity) { this.activity = activity; }
    private void ui(Runnable action) { activity.runOnUiThread(() -> { if (!activity.isFinishing() && !activity.isDestroyed()) action.run(); }); }
    private void message(String text) { Toast.makeText(activity,text,Toast.LENGTH_LONG).show(); }
    void check(boolean manual) {
        if (downloading.get()) { if (manual) message("正在下载更新。"); return; }
        long now = System.currentTimeMillis(), last = activity.getSharedPreferences("mobile-update",0).getLong("attempt",0);
        if (!manual && now >= last && now-last < 6*60*60*1000L) return;
        if (!checking.compareAndSet(false,true)) { if (manual) message("正在检查更新…"); return; }
        activity.getSharedPreferences("mobile-update",0).edit().putLong("attempt",now).apply();
        if (manual) message("正在检查手机版更新…");
        worker.execute(() -> {
            try {
                JSONObject wrapper = new JSONObject(new String(read(FEED,131072), StandardCharsets.UTF_8));
                JSONObject release = new JSONObject(new String(Base64.decode(wrapper.getString("content"),Base64.DEFAULT),StandardCharsets.UTF_8));
                validate(release);
                if (release.getInt("versionCode") <= BuildConfig.VERSION_CODE) { if (manual) ui(() -> message("已是最新版：" + BuildConfig.VERSION_NAME)); return; }
                ui(() -> new AlertDialog.Builder(activity).setTitle("知域 " + release.optString("versionName"))
                    .setMessage(release.optString("notes","手机版更新") + "\n\n下载后由系统确认安装，账号和数据会保留。")
                    .setNegativeButton("稍后",null).setPositiveButton("下载更新",(d,w) -> download(release)).show());
            } catch (Exception error) { if (manual) ui(() -> message("暂时无法检查更新，请稍后重试。")); }
            finally { checking.set(false); }
        });
    }
    private void validate(JSONObject release) throws Exception {
        if (release.getInt("protocol") != 1 || !BuildConfig.APPLICATION_ID.equals(release.getString("package"))
            || release.getInt("versionCode") <= 0 || release.getInt("minSdk") > Build.VERSION.SDK_INT
            || !CERTIFICATE.equals(release.getString("certificateSha256"))
            || !release.getString("sha256").matches("[a-f0-9]{64}")
            || release.getLong("size") <= 0 || release.getLong("size") > 30*1024*1024L
            || !release.getString("url").matches("https://github\\.com/L1nYux/FYrepo/releases/download/android-[a-zA-Z0-9.\\-]+/Zhiyu-[a-zA-Z0-9.\\-]+\\.apk")
            || !release.getString("versionName").matches("[0-9]+\\.[0-9]+\\.[0-9]+-mobile\\.[0-9]+")) throw new IllegalArgumentException("Invalid Android release");
    }
    private static boolean allowed(URL url) {
        String host = url.getHost();
        return "https".equals(url.getProtocol()) && url.getUserInfo() == null && (url.getPort() == -1 || url.getPort() == 443)
            && (host.equals("api.github.com") || host.equals("github.com") || host.endsWith(".githubusercontent.com"));
    }
    private HttpURLConnection connect(String address) throws Exception {
        URL url = new URL(address);
        for (int i=0;i<6;i++) {
            if (!allowed(url)) throw new IllegalArgumentException("Invalid update source");
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(15000); connection.setReadTimeout(20000); connection.setInstanceFollowRedirects(false);
            connection.setRequestProperty("User-Agent","ZhiyuAndroid/" + BuildConfig.VERSION_NAME);
            connection.setRequestProperty("Accept",url.getHost().equals("api.github.com") ? "application/vnd.github+json" : "application/octet-stream");
            try {
                int status = connection.getResponseCode();
                if (status >= 300 && status < 400) {
                    String location = connection.getHeaderField("Location"); if (location == null) throw new java.io.IOException();
                    url = new URL(url, location); connection.disconnect(); continue;
                }
                if (status != 200) throw new java.io.IOException();
                return connection;
            } catch (Exception error) { connection.disconnect(); throw error; }
        }
        throw new java.io.IOException("Too many redirects");
    }
    private byte[] read(String url,int limit) throws Exception {
        HttpURLConnection connection=connect(url);
        try (InputStream input=connection.getInputStream(); ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[8192];int count;
            while ((count=input.read(buffer)) != -1) { if (output.size()+count>limit) throw new java.io.IOException(); output.write(buffer,0,count); }
            return output.toByteArray();
        } finally { connection.disconnect(); }
    }
    private void download(JSONObject release) {
        if (!downloading.compareAndSet(false,true)) return;
        cancelled=false;
        progress=new AlertDialog.Builder(activity).setTitle("正在下载手机版更新")
            .setMessage("准备下载…").setNegativeButton("取消下载",(d,w) -> { cancelled=true; HttpURLConnection active=currentDownload; if(active!=null)active.disconnect(); })
            .setCancelable(false).create(); progress.show();
        worker.execute(() -> {
            File folder = new File(activity.getCacheDir(),"updates"), partial = new File(folder,"download.part"), apk=new File(folder,"latest.apk");
            boolean completed=false;
            try {
                validate(release); if (release.getInt("versionCode") <= BuildConfig.VERSION_CODE) throw new IllegalArgumentException();
                if (!folder.isDirectory() && !folder.mkdirs()) throw new java.io.IOException();
                long expected=release.getLong("size"), received=0, last=0;
                MessageDigest digest=MessageDigest.getInstance("SHA-256");
                HttpURLConnection connection=connect(release.getString("url")); currentDownload=connection;
                try (InputStream input=connection.getInputStream(); FileOutputStream output=new FileOutputStream(partial)) {
                    byte[] buffer=new byte[32768];int count;
                    while ((count=input.read(buffer)) != -1) {
                        if (cancelled) throw new java.io.IOException(); received+=count; if(received>expected)throw new java.io.IOException();
                        digest.update(buffer,0,count);output.write(buffer,0,count);
                        if(System.currentTimeMillis()-last>250){last=System.currentTimeMillis();final long bytes=received;
                            ui(() -> { if(progress!=null && progress.isShowing()) progress.setMessage("已下载 " + bytes*100/expected + "%"); });}
                    }
                } finally { connection.disconnect();currentDownload=null; }
                if(cancelled || received!=expected || !hex(digest.digest()).equals(release.getString("sha256"))) throw new java.io.IOException();
                verifyApk(partial,release);
                if(apk.exists() && !apk.delete())throw new java.io.IOException();
                if(!partial.renameTo(apk))throw new java.io.IOException();
                ready=release; completed=true;
                ui(() -> { if(progress!=null)progress.dismiss(); installReady(); });
            } catch(Exception error) { ui(() -> { if(progress!=null)progress.dismiss(); if(!cancelled)message("更新下载或校验失败，请重试。"); }); }
            finally { if(!completed)partial.delete(); downloading.set(false); }
        });
    }
    @SuppressWarnings("deprecation") private void verifyApk(File apk,JSONObject release) throws Exception {
        int flags=Build.VERSION.SDK_INT>=28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo info=activity.getPackageManager().getPackageArchiveInfo(apk.getPath(),flags);
        if(info==null || !BuildConfig.APPLICATION_ID.equals(info.packageName))throw new IllegalArgumentException();
        long version=Build.VERSION.SDK_INT>=28 ? info.getLongVersionCode() : info.versionCode;
        if(version!=release.getInt("versionCode") || version<=BuildConfig.VERSION_CODE || !release.getString("versionName").equals(info.versionName))throw new IllegalArgumentException();
        Signature[] signatures=Build.VERSION.SDK_INT>=28 && info.signingInfo!=null ? info.signingInfo.getApkContentsSigners() : info.signatures;
        if(signatures==null || signatures.length!=1 || !CERTIFICATE.equals(hex(MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()))))throw new IllegalArgumentException();
    }
    void installReady() {
        if (ready==null) return;
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            new AlertDialog.Builder(activity).setTitle("允许安装知域更新")
                .setMessage("请在系统设置中允许知域安装应用，返回后继续安装。")
                .setNegativeButton("稍后",null).setPositiveButton("前往设置",(d,w) -> {
                    try { activity.startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+BuildConfig.APPLICATION_ID)),INSTALL_PERMISSION); }
                    catch(Exception error){message("请在系统设置中允许知域安装应用。");}
                }).show(); return;
        }
        try {
            File apk=new File(new File(activity.getCacheDir(),"updates"),"latest.apk");verifyApk(apk,ready);
            Uri uri=Uri.parse("content://"+BuildConfig.APPLICATION_ID+".updates/latest.apk");
            Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            activity.startActivity(intent);
        } catch(Exception error){message("无法开始安装，请重新下载更新。");}
    }
    private static String hex(byte[] bytes) { StringBuilder result=new StringBuilder();for(byte b:bytes)result.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return result.toString(); }
    void close() { cancelled=true;HttpURLConnection active=currentDownload;if(active!=null)active.disconnect();worker.shutdownNow();if(progress!=null)progress.dismiss(); }
}
