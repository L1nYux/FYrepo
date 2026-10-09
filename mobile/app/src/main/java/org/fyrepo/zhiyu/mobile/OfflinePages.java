package org.fyrepo.zhiyu.mobile;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** Private, account-scoped GET cache. Writes and authentication always use the server. */
final class OfflinePages {
    interface Refresh { void ready(String address); }
    private final Context context;
    private final Refresh refresh;
    private final ExecutorService worker = Executors.newFixedThreadPool(2);
    private final Set<String> refreshing = ConcurrentHashMap.newKeySet();
    private final Set<String> freshOnce = ConcurrentHashMap.newKeySet();
    private volatile int generation;
    private volatile long forceUntil;
    OfflinePages(Context context, Refresh refresh) { this.context=context; this.refresh=refresh; }

    static boolean page(String path) {
        return path!=null && (path.equals("/messages/social/") || path.equals("/workspace/")
            || path.equals("/assistant/") || path.equals("/me/") || path.equals("/account/")
            || path.equals("/me/talent/") || path.equals("/me/appearance/") || path.equals("/me/files/") || path.matches("/files/(upload|legacy|attachment)/[1-9][0-9]*/") || path.equals("/me/usage/") || path.equals("/me/connections/")
            || path.equals("/messages/teams/") || path.equals("/messages/notices/") || path.equals("/messages/")
            || path.equals("/team-square/") || path.equals("/updates/")
            || path.matches("/updates/[1-9][0-9]*/") || path.equals("/app/pages/") || path.startsWith("/discover/")
            || path.matches("/(projects|tasks|experiments|documents)/(?:[1-9][0-9]*/)?")
            || path.matches("/messages/(personal|groups)/[1-9][0-9]*/"));
    }
    private boolean readable(WebResourceRequest request) {
        String path=request.getUrl().getPath();
        if(request.isForMainFrame()) return page(path);
        // Dynamic polling, login, tokens and management endpoints are not cached.
        return path!=null && (path.matches("/files/(upload|legacy|attachment)/[1-9][0-9]*/content/") || path.equals("/app/teams/") || path.equals("/app/preferences/") || path.equals("/messages/points/")
            || path.equals("/messages/local-records/state/") || path.matches("/members/[1-9][0-9]*/card/")
            || path.equals("/api-pool/catalog/") || path.equals("/assistant/conversations/")
            || path.matches("/accounts/[1-9][0-9]*/avatar/[^/]+/")
            || path.matches("/app/groups/[1-9][0-9]*/(avatar|image)/") || path.equals("/app/background/")
            || path.matches("/attachments/[1-9][0-9]*/download/")
            || path.matches("/messages/(files|legacy-files)/[1-9][0-9]*/")
            || path.matches("/messages/stickers/[1-9][0-9]*/file/") || path.equals("/messages/stickers/")
            || path.matches("/workspace/navigation/[1-9][0-9]*/")
            || path.matches("/documents/[1-9][0-9]*/images/[1-9][0-9]*/")
            || path.matches("/assistant/conversations/[1-9][0-9]*/")
            || path.matches("/messages/(personal|groups)/[1-9][0-9]*/history/"));
    }
    private String account(String origin) {
        return context.getSharedPreferences("connection",Context.MODE_PRIVATE).getString("account:"+origin,"");
    }
    private static String hash(String value) throws Exception {
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder text=new StringBuilder();for(byte b:bytes)text.append(String.format(Locale.ROOT,"%02x",b & 255));return text.toString();
    }
    private File directory(String origin) throws Exception {
        return new File(context.getFilesDir(),"page-cache/"+hash(origin+"\n"+account(origin)));
    }
    private File file(String origin,String url) throws Exception {return new File(directory(origin),hash(url)+".json");}
    private boolean online() {
        ConnectivityManager manager=(ConnectivityManager)context.getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkCapabilities caps=manager.getNetworkCapabilities(manager.getActiveNetwork());
        return caps!=null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }
    private JSONObject read(String origin,String url) {
        try {File f=file(origin,url);if(!f.isFile() || f.length()>13*1024*1024)return null;
            return new JSONObject(new String(Files.readAllBytes(f.toPath()),StandardCharsets.UTF_8));
        }catch(Exception ignored){return null;}
    }
    private void save(String origin,String url,JSONObject value) throws Exception {
        value.put("savedAt",System.currentTimeMillis());
        File dir=directory(origin);dir.mkdirs();File dest=file(origin,url),temp=File.createTempFile("page-",".tmp",dir);
        try {Files.write(temp.toPath(),value.toString().getBytes(StandardCharsets.UTF_8));
            Files.move(temp.toPath(),dest.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }finally{temp.delete();}
        File[] entries=dir.listFiles((d,n)->n.endsWith(".json"));if(entries==null)return;
        Arrays.sort(entries,Comparator.comparingLong(File::lastModified));long total=0;for(File f:entries)total+=f.length();
        for(File f:entries){if(total<=80L*1024*1024)break;if(!f.equals(dest)&&f.delete())total-=f.length();}
    }
    private JSONObject download(String origin,String url,Map<String,String> headers) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(url).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(4000);connection.setReadTimeout(8000);
        connection.setRequestProperty("Accept",headers.getOrDefault("Accept","text/html,application/json"));
        connection.setRequestProperty("User-Agent",headers.getOrDefault("User-Agent","ZhiyuMobile"));
        String cookies=CookieManager.getInstance().getCookie(origin);if(cookies!=null)connection.setRequestProperty("Cookie",cookies);
        try {
            int status=connection.getResponseCode();
            if(status==401 || status==403 || status==302 && String.valueOf(connection.getHeaderField("Location")).contains("/login/")) {
                clear(origin);return null;
            }
            if(status!=200)return null;
            String type=connection.getContentType();if(type==null || !(type.contains("text/html")||type.contains("application/json")||type.startsWith("image/")))return null;
            int limit=type.startsWith("image/")?8*1024*1024:2*1024*1024;
            ByteArrayOutputStream output=new ByteArrayOutputStream();try(InputStream input=connection.getInputStream()){
                byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1){output.write(buffer,0,count);if(output.size()>limit)return null;}
            }
            Map<String,String> responseHeaders=new HashMap<>();
            for(Map.Entry<String,List<String>> entry:connection.getHeaderFields().entrySet()){
                String key=entry.getKey();if(key==null)continue;
                if(key.equalsIgnoreCase("Set-Cookie")){for(String cookie:entry.getValue())CookieManager.getInstance().setCookie(origin,cookie);}
                else if(!key.equalsIgnoreCase("Content-Length")&&!key.equalsIgnoreCase("Content-Encoding")&&!key.equalsIgnoreCase("Transfer-Encoding"))responseHeaders.put(key,String.join(",",entry.getValue()));
            }
            return new JSONObject().put("mime",type.split(";",2)[0]).put("body",android.util.Base64.encodeToString(output.toByteArray(),android.util.Base64.NO_WRAP)).put("headers",new JSONObject(responseHeaders));
        }finally{connection.disconnect();}
    }
    private WebResourceResponse response(JSONObject value,boolean cached,boolean stale) throws Exception {
        Map<String,String> headers=new HashMap<>();JSONObject stored=value.getJSONObject("headers");
        for(Iterator<String> i=stored.keys();i.hasNext();){String key=i.next();headers.put(key,stored.getString(key));}
        byte[] body=android.util.Base64.decode(value.getString("body"),android.util.Base64.DEFAULT);
        if(cached && value.getString("mime").equals("text/html")) {
            String html=new String(body,StandardCharsets.UTF_8);
            // Revalidate in place after a paint; unavailable data stays in its usual page.
            String notice="<div id='phone-cache-state' role='status' style='padding:6px 12px;background:#eef3ef;color:#526257;font-size:12px'>"+(stale?"离线 · 显示本地缓存":"本地缓存")+"</div>";
            html=html.replaceFirst("(?i)(<body[^>]*>)","$1"+notice);body=html.getBytes(StandardCharsets.UTF_8);
        }
        return new WebResourceResponse(value.getString("mime"),"UTF-8",200,"OK",headers,new ByteArrayInputStream(body));
    }
    WebResourceResponse intercept(String origin,WebResourceRequest request) {
        String url=request.getUrl().toString();if(!"GET".equals(request.getMethod()) || !readable(request) || !account(origin).matches("[1-9][0-9]*"))return null;
        int epoch=generation;JSONObject cached=read(origin,url);boolean connected=online();
        if(cached!=null && freshOnce.remove(url))try{return response(cached,false,false);}catch(Exception ignored){}
        if(cached==null && !connected && request.isForMainFrame()) {
            String html="<!doctype html><html lang='zh-CN' data-account='"+account(origin)+"' data-offline-empty='true'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head><body><main><p style='padding:20px'>此页面尚无本地缓存，联网打开一次后即可离线查看。</p></main></body></html>";
            return new WebResourceResponse("text/html","UTF-8",new ByteArrayInputStream(html.getBytes(StandardCharsets.UTF_8)));
        }
        long maxAge=request.isForMainFrame()?120000L:cached!=null && cached.optString("mime").startsWith("image/")?86400000L:60000L;
        if(cached!=null && (!connected || System.currentTimeMillis()>forceUntil)) {
            if(connected && System.currentTimeMillis()-cached.optLong("savedAt")>maxAge && refreshing.add(url))worker.execute(()->{try{
                JSONObject value=download(origin,url,request.getRequestHeaders());
                if(value!=null && epoch==generation){save(origin,url,value);if(request.isForMainFrame()){freshOnce.add(url);refresh.ready(url);}}
            }catch(Exception ignored){}finally{refreshing.remove(url);}});
            try{return response(cached,true,!connected);}catch(Exception ignored){}
        }
        try {JSONObject value=download(origin,url,request.getRequestHeaders());
            if(value!=null && epoch==generation){save(origin,url,value);return response(value,false,false);}
        }catch(Exception ignored){if(cached!=null && epoch==generation)try{return response(cached,true,true);}catch(Exception ignoredAgain){}}
        return null;
    }
    void clear(String origin) {
        generation++;freshOnce.clear();
        try {File[] entries=directory(origin).listFiles();if(entries!=null)for(File f:entries)if(f.isFile())f.delete();}catch(Exception ignored){}
    }
    void remember(String origin,String url,String html) {
        if(!page(Uri.parse(url).getPath()) || !account(origin).matches("[1-9][0-9]*") || html.length()>2*1024*1024 || html.contains("phone-cache-state") || html.contains("data-offline-empty"))return;
        int epoch=generation;
        worker.execute(()->{try {if(epoch==generation)save(origin,url,new JSONObject().put("mime","text/html")
            .put("body",android.util.Base64.encodeToString(html.getBytes(StandardCharsets.UTF_8),android.util.Base64.NO_WRAP)).put("headers",new JSONObject()));
        }catch(Exception ignored){}});
    }
    void close(){generation++;worker.shutdownNow();}
    void force(){forceUntil=System.currentTimeMillis()+10000;}
}
