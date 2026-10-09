package org.fyrepo.zhiyu.mobile;

import android.app.Service;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.IBinder;
import android.webkit.CookieManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/** Opt-in bounded background synchronization. No reboot/autostart or wake lock. */
public final class MessageNotifications extends Service {
    public static volatile boolean foreground;
    private final ScheduledExecutorService worker=Executors.newSingleThreadScheduledExecutor();
    private final HashMap<String,Long> cursors=new HashMap<>();
    private String identity="";
    private boolean initialized;
    private NotificationManager manager;
    private volatile boolean closed;
    @Override public void onCreate(){super.onCreate();manager=getSystemService(NotificationManager.class);
        NotificationChannel sync=new NotificationChannel("message-sync","后台消息同步",NotificationManager.IMPORTANCE_LOW);sync.setShowBadge(false);manager.createNotificationChannel(sync);
        NotificationChannel messages=new NotificationChannel("chat-messages","聊天消息",NotificationManager.IMPORTANCE_HIGH);messages.setShowBadge(true);manager.createNotificationChannel(messages);NotificationChannel important=new NotificationChannel("important-group-messages","群重要消息",NotificationManager.IMPORTANCE_HIGH);important.setShowBadge(false);manager.createNotificationChannel(important);
        Intent stop=new Intent(this,MessageNotifications.class).setAction("stop");
        Notification notification=new Notification.Builder(this,"message-sync").setSmallIcon(R.drawable.notification_chat).setContentTitle("知域消息提醒已开启").setContentText("正在后台同步，可随时关闭").setOngoing(true).addAction(new Notification.Action.Builder(null,"关闭提醒",PendingIntent.getService(this,1,stop,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE)).build()).build();
        startForeground(9000,notification);worker.scheduleWithFixedDelay(this::poll,0,30,TimeUnit.SECONDS);
    }
    @Override public int onStartCommand(Intent intent,int flags,int id){if(intent!=null&&"stop".equals(intent.getAction())){getSharedPreferences("connection",MODE_PRIVATE).edit().putBoolean("background-messages",false).apply();stopSelf();}return START_NOT_STICKY;}
    private void poll(){if(closed)return;HttpURLConnection connection=null;try{
        SharedPreferences prefs=getSharedPreferences("connection",MODE_PRIVATE);String server=prefs.getString("origin","http://47.117.89.248"),account=prefs.getString("account:"+server,"");
        if(account.isEmpty()||!prefs.getBoolean("background-messages",false)){stopSelf();return;}
        if(!identity.equals(server+"|"+account)){clearMessages(this);identity=server+"|"+account;cursors.clear();initialized=false;
            if(identity.equals(prefs.getString("notification-cursor-identity",""))){
                try{JSONObject stored=new JSONObject(prefs.getString("notification-cursors","{}"));java.util.Iterator<String> keys=stored.keys();while(keys.hasNext()){String key=keys.next();cursors.put(key,stored.getLong(key));}initialized=true;}catch(Exception ignored){}
            }}
        connection=(HttpURLConnection)new URL(server+"/app/notifications/").openConnection();connection.setConnectTimeout(10000);connection.setReadTimeout(10000);connection.setInstanceFollowRedirects(false);connection.setRequestProperty("Accept","application/json");String cookie=CookieManager.getInstance().getCookie(server);if(cookie!=null)connection.setRequestProperty("Cookie",cookie);
        int code=connection.getResponseCode();if(code==401||code==302){clearMessages(this);stopSelf();return;}if(code!=200||!String.valueOf(connection.getContentType()).contains("application/json"))return;
        byte[] bytes;try(java.io.InputStream in=connection.getInputStream()){java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();byte[] chunk=new byte[8192];int count;while((count=in.read(chunk))>=0){out.write(chunk,0,count);if(out.size()>262144)break;}bytes=out.toByteArray();}if(bytes.length>262144)return;
        JSONObject data=new JSONObject(new String(bytes,StandardCharsets.UTF_8));if(!account.equals(data.optString("account"))){stopSelf();return;}
        if(!identity.equals(prefs.getString("origin","http://47.117.89.248")+"|"+prefs.getString("account:"+server,""))||closed)return;
        JSONArray items=data.optJSONArray("conversations");if(items==null)return;int total=data.optInt("total");
        for(int i=0;i<items.length();i++){JSONObject item=items.getJSONObject(i);String key=item.getString("key");long next=item.optLong("message_id"),before=cursors.getOrDefault(key,0L);int notificationId=10000+(key.hashCode()&0x3fffffff);
            if(item.optInt("unread")==0||!item.optBoolean("popup"))manager.cancel(notificationId);
            if(initialized&&!foreground&&next>before&&item.optBoolean("popup")){
                String route=item.getString("url");if(!route.matches("/messages/(personal|groups)/[1-9][0-9]*/"))continue;
                Intent open=new Intent(this,MainActivity.class).putExtra("message-account",account).putExtra("message-origin",server).putExtra("message-path",route).setFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
                Notification message=new Notification.Builder(this,key.startsWith("person:")?"chat-messages":"important-group-messages").setSmallIcon(R.drawable.notification_chat).setContentTitle(item.optString("title","新消息")).setContentText(item.optString("label")+item.optString("preview")).setStyle(new Notification.BigTextStyle().bigText(item.optString("label")+item.optString("preview"))).setNumber(item.optInt("badge")).setGroup("zhiyu-messages").setAutoCancel(true).setContentIntent(PendingIntent.getActivity(this,notificationId,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE)).build();
                manager.notify(notificationId,message);
            }
            cursors.put(key,Math.max(before,next));
        }
        initialized=true;
        JSONObject stored=new JSONObject();for(java.util.Map.Entry<String,Long> entry:cursors.entrySet())stored.put(entry.getKey(),entry.getValue());
        prefs.edit().putString("notification-cursor-identity",identity).putString("notification-cursors",stored.toString()).apply();
    }catch(Exception ignored){/* A transient connection failure retries on the next interval. */}finally{if(connection!=null)connection.disconnect();}}
    @Override public void onTimeout(int startId,int type){stopForeground(STOP_FOREGROUND_REMOVE);stopSelf();}
    @Override public void onDestroy(){closed=true;worker.shutdownNow();stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy();}
    public static void clearMessages(android.content.Context context){NotificationManager manager=context.getSystemService(NotificationManager.class);for(android.service.notification.StatusBarNotification item:manager.getActiveNotifications()){String channel=item.getNotification().getChannelId();if("chat-messages".equals(channel)||"important-group-messages".equals(channel))manager.cancel(item.getId());}}
    @Override public IBinder onBind(Intent intent){return null;}
}
