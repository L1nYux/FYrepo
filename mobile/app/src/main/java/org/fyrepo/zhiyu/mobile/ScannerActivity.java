package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;
import java.util.*;
import java.util.concurrent.*;

/** All QR decoding happens on this phone. Camera and selected photos stay local. */
@SuppressWarnings("deprecation")
public final class ScannerActivity extends Activity implements SurfaceHolder.Callback {
    private Camera camera;
    private SurfaceView preview;
    private FrameLayout previewHost;
    private TextView status;
    private ScanControl torch;
    private boolean surfaceReady,finished,foreground,torchOn;
    private volatile boolean decoding;
    private long lastFrame;
    private float pinchDistance;
    private String pendingAlbum;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private int dp(float value){return Math.round(value*getResources().getDisplayMetrics().density);}
    @Override public void onCreate(Bundle state){super.onCreate(state);
        getWindow().setStatusBarColor(0xff000000);getWindow().setNavigationBarColor(0xff000000);
        getWindow().getDecorView().setSystemUiVisibility(0);
        FrameLayout root=new FrameLayout(this);root.setBackgroundColor(0xff000000);root.setFitsSystemWindows(true);
        previewHost=new FrameLayout(this);previewHost.setClipChildren(true);preview=new SurfaceView(this);preview.getHolder().addCallback(this);previewHost.addView(preview,new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));root.addView(previewHost,new FrameLayout.LayoutParams(-1,-1));
        View overlay=new ScanOverlay();root.addView(overlay,new FrameLayout.LayoutParams(-1,-1));overlay.setOnTouchListener((v,e)->{
            if(camera==null)return true;
            if(e.getPointerCount()==2){float distance=(float)Math.hypot(e.getX(0)-e.getX(1),e.getY(0)-e.getY(1));if(e.getActionMasked()==MotionEvent.ACTION_POINTER_DOWN)pinchDistance=distance;else if(e.getActionMasked()==MotionEvent.ACTION_MOVE&&Math.abs(distance-pinchDistance)>dp(12)){try{Camera.Parameters p=camera.getParameters();if(p.isZoomSupported()){p.setZoom(Math.max(0,Math.min(p.getMaxZoom(),p.getZoom()+(distance>pinchDistance?1:-1))));camera.setParameters(p);}pinchDistance=distance;}catch(Exception ignored){}}}
            else if(e.getAction()==MotionEvent.ACTION_UP)try{camera.autoFocus((ok,c)->{});}catch(Exception ignored){}return true;
        });
        LinearLayout top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);top.setPadding(dp(12),dp(8),dp(12),0);
        ScanControl close=new ScanControl("close","",false);close.setContentDescription("关闭扫一扫");close.setOnClickListener(v->finish());top.addView(close,new LinearLayout.LayoutParams(dp(48),dp(48)));
        TextView title=new TextView(this);title.setText("扫一扫");title.setTextSize(18);title.setTextColor(-1);title.setGravity(Gravity.CENTER);top.addView(title,new LinearLayout.LayoutParams(0,dp(48),1));
        ScanControl help=new ScanControl("help","",false);help.setContentDescription("扫码帮助");help.setOnClickListener(v->status.setText("将二维码对准取景框，也可从相册选择；双指缩放，轻点画面对焦。"));top.addView(help,new LinearLayout.LayoutParams(dp(48),dp(48)));root.addView(top,new FrameLayout.LayoutParams(-1,dp(64),Gravity.TOP));
        LinearLayout bottom=new LinearLayout(this);bottom.setOrientation(LinearLayout.VERTICAL);bottom.setPadding(dp(20),dp(16),dp(20),dp(24));bottom.setBackground(new android.graphics.drawable.GradientDrawable(android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,new int[]{0x00000000,0xe6000000}));
        status=new TextView(this);status.setText("将二维码放入取景框内");status.setTextSize(14);status.setTextColor(-1);status.setGravity(Gravity.CENTER);status.setMinHeight(dp(48));bottom.addView(status,new LinearLayout.LayoutParams(-1,-2));
        torch=new ScanControl("torch","轻触照亮",true);torch.setOnClickListener(v->toggleTorch());LinearLayout.LayoutParams torchLayout=new LinearLayout.LayoutParams(dp(100),dp(80));torchLayout.gravity=Gravity.CENTER_HORIZONTAL;torchLayout.bottomMargin=dp(20);bottom.addView(torch,torchLayout);
        LinearLayout actions=new LinearLayout(this);actions.setGravity(Gravity.CENTER_VERTICAL);
        ScanControl qr=new ScanControl("qr","我的二维码",false);qr.setOnClickListener(v->{finished=true;stop();setResult(RESULT_OK,new Intent().putExtra("route","/app/pages/?view=my-qr"));finish();});actions.addView(qr,new LinearLayout.LayoutParams(0,dp(64),1));
        ScanControl album=new ScanControl("album","相册",false);album.setOnClickListener(v->pickImage());actions.addView(album,new LinearLayout.LayoutParams(dp(90),dp(64)));bottom.addView(actions);root.addView(bottom,new FrameLayout.LayoutParams(-1,-2,Gravity.BOTTOM));setContentView(root);
        if(checkSelfPermission(android.Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{android.Manifest.permission.CAMERA},1);
    }
    private void pickImage(){Intent pick=android.os.Build.VERSION.SDK_INT>=33?new Intent("android.provider.action.PICK_IMAGES"):new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);pick.setType("image/*");try{startActivityForResult(pick,2);}catch(Exception e){status.setText("手机未提供照片选择器。");}}
    private void toggleTorch(){if(camera==null){status.setText("请先开启相机权限。");return;}try{Camera.Parameters p=camera.getParameters();List<String> modes=p.getSupportedFlashModes();if(modes==null||!modes.contains(Camera.Parameters.FLASH_MODE_TORCH)){status.setText("此相机不支持手电筒。");return;}torchOn=!torchOn;p.setFlashMode(torchOn?Camera.Parameters.FLASH_MODE_TORCH:Camera.Parameters.FLASH_MODE_OFF);camera.setParameters(p);torch.setSelected(torchOn);torch.label=torchOn?"轻触关闭":"轻触照亮";torch.invalidate();}catch(Exception e){torchOn=false;status.setText("手电筒暂不可用。");}}
    private MultiFormatReader reader(){MultiFormatReader r=new MultiFormatReader();EnumMap<DecodeHintType,Object> hints=new EnumMap<>(DecodeHintType.class);hints.put(DecodeHintType.POSSIBLE_FORMATS,Collections.singletonList(BarcodeFormat.QR_CODE));hints.put(DecodeHintType.TRY_HARDER,true);r.setHints(hints);return r;}
    private String decode(LuminanceSource source)throws NotFoundException {MultiFormatReader r=reader();try{return r.decodeWithState(new BinaryBitmap(new HybridBinarizer(source))).getText();}catch(NotFoundException e){r.reset();return r.decodeWithState(new BinaryBitmap(new HybridBinarizer(source.invert()))).getText();}finally{r.reset();}}
    private void start(){if(camera!=null||!surfaceReady||!foreground||finished||checkSelfPermission(android.Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)return;try{
        int id=0;Camera.CameraInfo info=new Camera.CameraInfo();for(int i=0;i<Camera.getNumberOfCameras();i++){Camera.getCameraInfo(i,info);if(info.facing==Camera.CameraInfo.CAMERA_FACING_BACK){id=i;break;}}Camera.getCameraInfo(id,info);camera=Camera.open(id);
        Camera.Parameters p=camera.getParameters();List<String> modes=p.getSupportedFocusModes();if(modes!=null&&modes.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE))p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);Camera.Size chosen=null;for(Camera.Size size:p.getSupportedPreviewSizes())if(size.width<=1280&&(chosen==null||size.width>chosen.width))chosen=size;if(chosen!=null)p.setPreviewSize(chosen.width,chosen.height);camera.setParameters(p);
        int rotation=getWindowManager().getDefaultDisplay().getRotation()*90;int orientation=info.facing==Camera.CameraInfo.CAMERA_FACING_FRONT?(360-(info.orientation+rotation)%360)%360:(info.orientation-rotation+360)%360;camera.setDisplayOrientation(orientation);Camera.Size shape=camera.getParameters().getPreviewSize();final float ratio=orientation%180==0?(float)shape.width/shape.height:(float)shape.height/shape.width;
        previewHost.post(()->{int w=previewHost.getWidth(),h=previewHost.getHeight();if(w<=0||h<=0)return;if((float)w/h>ratio)h=Math.round(w/ratio);else w=Math.round(h*ratio);preview.setLayoutParams(new FrameLayout.LayoutParams(w,h,Gravity.CENTER));});
        camera.setPreviewDisplay(preview.getHolder());camera.setPreviewCallback((bytes,source)->{if(decoding||finished||!foreground||System.currentTimeMillis()-lastFrame<450)return;Camera.Size size=source.getParameters().getPreviewSize();byte[] frame=bytes.clone();decoding=true;lastFrame=System.currentTimeMillis();worker.execute(()->{try{complete(decode(new PlanarYUVLuminanceSource(frame,size.width,size.height,0,0,size.width,size.height,false)));}catch(Exception ignored){}finally{decoding=false;}});});camera.startPreview();status.setText("将二维码放入取景框内");
        List<String> flash=camera.getParameters().getSupportedFlashModes();torch.setVisibility(flash!=null&&flash.contains(Camera.Parameters.FLASH_MODE_TORCH)?View.VISIBLE:View.INVISIBLE);
    }catch(Exception e){stop();status.setText("相机暂不可用，可以从相册识别。");}}
    private void stop(){Camera old=camera;camera=null;torchOn=false;if(torch!=null){torch.setSelected(false);torch.label="轻触照亮";torch.invalidate();}if(old!=null){try{old.setPreviewCallback(null);old.stopPreview();}catch(Exception ignored){}finally{old.release();}}}
    private void complete(String value){runOnUiThread(()->{if(finished||!foreground)return;finished=true;stop();setResult(RESULT_OK,new Intent().putExtra("code",value));finish();});}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=2||result!=RESULT_OK||data==null||data.getData()==null)return;status.setText("正在识别…");decoding=true;worker.execute(()->{Bitmap bitmap=null;try{
        if(android.os.Build.VERSION.SDK_INT>=28)bitmap=ImageDecoder.decodeBitmap(ImageDecoder.createSource(getContentResolver(),data.getData()),(decoder,info,source)->{decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);decoder.setTargetSampleSize(Math.max(1,(Math.max(info.getSize().getWidth(),info.getSize().getHeight())+1799)/1800));});
        else{android.graphics.BitmapFactory.Options options=new android.graphics.BitmapFactory.Options();options.inJustDecodeBounds=true;try(java.io.InputStream in=getContentResolver().openInputStream(data.getData())){bitmap=BitmapFactory.decodeStream(in,null,options);}options.inJustDecodeBounds=false;options.inSampleSize=Math.max(1,(Math.max(options.outWidth,options.outHeight)+1799)/1800);try(java.io.InputStream in=getContentResolver().openInputStream(data.getData())){bitmap=BitmapFactory.decodeStream(in,null,options);}}
        if(bitmap==null)throw new IllegalStateException();String value=null;for(int turn=0;turn<4&&value==null;turn++){Bitmap rotated=bitmap;if(turn>0){Matrix m=new Matrix();m.postRotate(turn*90);rotated=Bitmap.createBitmap(bitmap,0,0,bitmap.getWidth(),bitmap.getHeight(),m,true);}try{int w=rotated.getWidth(),h=rotated.getHeight();int[] pixels=new int[w*h];rotated.getPixels(pixels,0,w,0,0,w,h);value=decode(new RGBLuminanceSource(w,h,pixels));}catch(NotFoundException ignored){}finally{if(rotated!=bitmap)rotated.recycle();}}if(value==null)throw new IllegalStateException();final String code=value;runOnUiThread(()->{if(foreground)complete(code);else pendingAlbum=code;});
    }catch(Exception e){runOnUiThread(()->status.setText("没有识别到二维码，请选择清晰图片。"));}finally{if(bitmap!=null)bitmap.recycle();decoding=false;}});}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==1){if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)start();else status.setText("相机权限未开启，仍可从相册识别。");}}
    @Override protected void onResume(){super.onResume();foreground=true;if(pendingAlbum!=null){String code=pendingAlbum;pendingAlbum=null;complete(code);}else start();}
    @Override protected void onPause(){foreground=false;stop();super.onPause();}
    @Override protected void onDestroy(){worker.shutdown();super.onDestroy();}
    @Override public void surfaceCreated(SurfaceHolder holder){surfaceReady=true;start();}
    @Override public void surfaceChanged(SurfaceHolder holder,int format,int w,int h){}
    @Override public void surfaceDestroyed(SurfaceHolder holder){surfaceReady=false;stop();}
    private final class ScanOverlay extends View{
        final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);ScanOverlay(){super(ScannerActivity.this);}
        @Override protected void onDraw(Canvas c){float w=getWidth(),h=getHeight(),side=Math.min(w*.72f,h*.42f),left=(w-side)/2,top=(h-side)/2-dp(60);top=Math.max(dp(90),top);p.setColor(0x65000000);p.setStyle(Paint.Style.FILL);c.drawRect(0,0,w,top,p);c.drawRect(0,top+side,w,h,p);c.drawRect(0,top,left,top+side,p);c.drawRect(left+side,top,w,top+side,p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(dp(3));p.setColor(0xff07c160);float len=dp(22);for(int i=0;i<4;i++){float x=i%2==0?left:left+side,y=i<2?top:top+side;c.drawLine(x,y,x+(i%2==0?len:-len),y,p);c.drawLine(x,y,x,y+(i<2?len:-len),p);}float y=top+side*((System.currentTimeMillis()%2500)/2500f);p.setStrokeWidth(dp(2));c.drawLine(left+dp(8),y,left+side-dp(8),y,p);if(foreground)postInvalidateDelayed(32);}
    }
    private final class ScanControl extends View{
        String kind,label;boolean vertical;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);ScanControl(String kind,String label,boolean vertical){super(ScannerActivity.this);this.kind=kind;this.label=label;this.vertical=vertical;setContentDescription(label);setFocusable(true);setClickable(true);}
        @Override protected void onDraw(Canvas c){super.onDraw(c);p.setColor(isSelected()?0xff07c160:0xffffffff);p.setStrokeWidth(dp(2));p.setStyle(Paint.Style.STROKE);float x=vertical?getWidth()/2f:dp(24),y=vertical?dp(24):getHeight()/2f,r=dp(10);
            if(kind.equals("close")){c.drawLine(x-r,y-r,x+r,y+r,p);c.drawLine(x+r,y-r,x-r,y+r,p);}
            else if(kind.equals("album")){c.drawRoundRect(x-r,y-r,x+r,y+r,dp(2),dp(2),p);Path path=new Path();path.moveTo(x-r,y+r/2);path.lineTo(x-r/3,y-r/4);path.lineTo(x+r/3,y+r/2);path.lineTo(x+r,y);c.drawPath(path,p);c.drawCircle(x+r/3,y-r/2,dp(1),p);}
            else if(kind.equals("qr")){for(int i=0;i<3;i++){float ax=x-r+(i%2)*r*1.3f,ay=y-r+(i/2)*r*1.3f;c.drawRect(ax,ay,ax+r*.7f,ay+r*.7f,p);}c.drawLine(x+dp(3),y+dp(4),x+r,y+r,p);}
            else if(kind.equals("torch")){Path path=new Path();path.moveTo(x-r,y-r);path.lineTo(x+r,y-r);path.lineTo(x+r,y-r/3);path.lineTo(x+r/3,y+r/3);path.lineTo(x+r/3,y+r*1.5f);path.lineTo(x-r/3,y+r*1.5f);path.lineTo(x-r/3,y+r/3);path.lineTo(x-r,y-r/3);path.close();c.drawPath(path,p);}
            else{c.drawCircle(x,y,r,p);p.setStyle(Paint.Style.FILL);p.setTextSize(dp(15));p.setTextAlign(Paint.Align.CENTER);c.drawText("?",x,y+dp(5),p);}
            if(!label.isEmpty()){p.setStyle(Paint.Style.FILL);p.setTextSize(dp(14));p.setTextAlign(vertical?Paint.Align.CENTER:Paint.Align.LEFT);c.drawText(label,vertical?getWidth()/2f:dp(44),vertical?dp(64):getHeight()/2f+dp(5),p);}
        }
    }
}
