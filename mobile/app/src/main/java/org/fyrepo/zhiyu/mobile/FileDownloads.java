package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.*;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.CookieManager;
import android.widget.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.*;

/** Authenticated downloads, app-owned public folder and cancellable progress. */
final class FileDownloads {
    private final Activity activity;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private volatile boolean cancelled;
    private volatile boolean busy;
    private volatile HttpURLConnection active;
    private AlertDialog dialog;
    FileDownloads(Activity activity){this.activity=activity;}
    static boolean sameOrigin(String origin,String url){try{URI a=new URI(origin),b=new URI(url);return b.getUserInfo()==null&&a.getScheme().equals(b.getScheme())&&a.getHost().equals(b.getHost())&&a.getPort()==b.getPort();}catch(Exception e){return false;}}
    void start(String origin,String account,String address,String filename,String type,boolean open){
        if(account==null||!account.matches("[1-9][0-9]*")||!sameOrigin(origin,address))return;
        if(busy){Toast.makeText(activity,"请先完成或取消当前下载。",Toast.LENGTH_SHORT).show();return;}
        String name=filename.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]","_");if(name.isEmpty())name="附件";if(name.length()>180)name=name.substring(0,180);
        final String safeName=name,cookie=CookieManager.getInstance().getCookie(address);
        final String mime=type==null||type.isEmpty()?"application/octet-stream":type;
        cancelled=false;busy=true;
        LinearLayout layout=new LinearLayout(activity);layout.setOrientation(LinearLayout.VERTICAL);int pad=(int)(24*activity.getResources().getDisplayMetrics().density);layout.setPadding(pad,pad/2,pad,pad/2);
        TextView label=new TextView(activity);label.setText("准备下载…");ProgressBar bar=new ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal);bar.setMax(100);bar.setIndeterminate(true);layout.addView(label);layout.addView(bar);
        dialog=new AlertDialog.Builder(activity).setTitle(safeName).setView(layout).setNegativeButton("取消下载",(d,w)->cancel()).setOnCancelListener(d->cancel()).create();dialog.show();
        worker.execute(()->{
            Uri saved=null;boolean created=false;OutputStream output=null;File partial=null;
            try{
                String key=hash(origin+"\n"+account+"\n"+address);
                android.content.SharedPreferences prefs=activity.getSharedPreferences("file-downloads",Context.MODE_PRIVATE);
                String prior=prefs.getString(key,"");
                if(!prior.isEmpty()){
                    Uri previous=Uri.parse(prior);try(InputStream check=activity.getContentResolver().openInputStream(previous)){if(check!=null){complete(previous,mime,open);return;}}catch(Exception missing){}
                }
                String url=address;HttpURLConnection connection=null;boolean responseReady=false;
                for(int redirects=0;redirects<5;redirects++){
                    if(cancelled||!sameOrigin(origin,url))throw new IOException("下载已取消或地址无效");
                    connection=(HttpURLConnection)new URL(url).openConnection();active=connection;connection.setConnectTimeout(20000);connection.setReadTimeout(60000);connection.setInstanceFollowRedirects(false);
                    if(cookie!=null)connection.setRequestProperty("Cookie",cookie);
                    int code=connection.getResponseCode();
                    if(code>=300&&code<400){String next=connection.getHeaderField("Location");if(next==null)throw new IOException("无效跳转");url=new URL(new URL(url),next).toString();connection.disconnect();continue;}
                    String disposition=connection.getHeaderField("Content-Disposition");
                    if(code!=200||connection.getContentType()!=null&&connection.getContentType().toLowerCase().contains("text/html")&&(disposition==null||!disposition.toLowerCase().contains("attachment")))throw new IOException("请重新登录后重试");responseReady=true;break;
                }
                if(!responseReady)throw new IOException("文件跳转次数过多，请重试");
                if(connection==null||connection.getResponseCode()!=200)throw new IOException("下载地址不可用");
                if(Build.VERSION.SDK_INT>=29){ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,safeName);values.put(MediaStore.Downloads.MIME_TYPE,mime);values.put(MediaStore.Downloads.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/知域");values.put(MediaStore.Downloads.IS_PENDING,1);saved=activity.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(saved==null)throw new IOException("无法保存文件");created=true;output=activity.getContentResolver().openOutputStream(saved);}
                else{File dir=new File(activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS),"知域");dir.mkdirs();partial=new File(dir,key+"-"+safeName);saved=Uri.parse("content://"+activity.getPackageName()+".downloads/"+partial.getName());output=new FileOutputStream(partial);}
                created=true;if(output==null)throw new IOException("无法保存文件");
                long total=connection.getContentLengthLong(),count=0,lastUpdate=0;
                try(InputStream in=connection.getInputStream();OutputStream out=output){output=null;byte[] bytes=new byte[32768];int n;while((n=in.read(bytes))>=0){if(cancelled)throw new IOException("已取消");out.write(bytes,0,n);count+=n;if(System.currentTimeMillis()-lastUpdate>200){lastUpdate=System.currentTimeMillis();final long done=count;activity.runOnUiThread(()->{bar.setIndeterminate(total<=0);if(total>0)bar.setProgress((int)Math.min(100,done*100/total));label.setText(total>0?done*100/total+"% · "+done/1024+" / "+total/1024+" KB":done/1024+" KB");});}}}
                if(cancelled||total>=0&&count!=total)throw new IOException("文件未下载完整");
                if(Build.VERSION.SDK_INT>=29){ContentValues values=new ContentValues();values.put(MediaStore.Downloads.IS_PENDING,0);activity.getContentResolver().update(saved,values,null,null);}
                prefs.edit().putString(key,saved.toString()).apply();complete(saved,mime,open);
            }catch(Exception e){if(created){if(partial!=null)partial.delete();else if(saved!=null)activity.getContentResolver().delete(saved,null,null);}final String message=cancelled?"下载已取消":"下载失败，请重试。";activity.runOnUiThread(()->{if(dialog!=null)dialog.dismiss();Toast.makeText(activity,message,Toast.LENGTH_LONG).show();});}
            finally{if(active!=null)active.disconnect();active=null;if(output!=null)try{output.close();}catch(Exception ignored){}busy=false;}
        });
    }
    private void complete(Uri uri,String mime,boolean open){activity.runOnUiThread(()->{if(dialog!=null)dialog.dismiss();if(cancelled||activity.isFinishing())return;if(open){Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);intent.setClipData(ClipData.newRawUri("附件",uri));try{activity.startActivity(Intent.createChooser(intent,"打开文件"));}catch(ActivityNotFoundException e){Toast.makeText(activity,"没有可打开此文件的应用。文件已保存。",Toast.LENGTH_LONG).show();}}else Toast.makeText(activity,Build.VERSION.SDK_INT>=29?"已保存到 下载 / 知域":"已保存到知域的下载目录",Toast.LENGTH_LONG).show();});}
    private static String hash(String value)throws Exception{byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder result=new StringBuilder();for(byte b:bytes)result.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return result.toString();}
    void cancel(){cancelled=true;if(active!=null)active.disconnect();}
    void close(){cancel();if(dialog!=null)dialog.dismiss();worker.shutdownNow();}
}
