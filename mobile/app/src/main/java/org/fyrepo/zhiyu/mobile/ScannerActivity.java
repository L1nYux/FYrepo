package org.fyrepo.zhiyu.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.ImageDecoder;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;
import java.util.EnumMap;
import java.util.Collections;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Locally decodes QR codes. No camera frame or album image is uploaded. */
@SuppressWarnings("deprecation")
public final class ScannerActivity extends Activity implements SurfaceHolder.Callback {
    private Camera camera;
    private SurfaceView preview;private android.widget.FrameLayout previewHost;
    private TextView status;
    private boolean surfaceReady,decoding,finished,foreground;
    private long lastFrame;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    @Override public void onCreate(Bundle state){super.onCreate(state);
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setFitsSystemWindows(true);root.setBackgroundColor(0xff151918);
        TextView title=new TextView(this);title.setText("扫一扫");title.setTextColor(0xffffffff);title.setTextSize(20);title.setGravity(Gravity.CENTER);root.addView(title,new LinearLayout.LayoutParams(-1,64));
        preview=new SurfaceView(this);preview.getHolder().addCallback(this);previewHost=new android.widget.FrameLayout(this);previewHost.addView(preview,new android.widget.FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));root.addView(previewHost,new LinearLayout.LayoutParams(-1,0,1));
        status=new TextView(this);status.setText("将二维码放入画面中");status.setTextColor(0xffffffff);status.setGravity(Gravity.CENTER);root.addView(status,new LinearLayout.LayoutParams(-1,72));
        LinearLayout actions=new LinearLayout(this);Button album=new Button(this);album.setText("从相册识别");album.setOnClickListener(v->{Intent pick=android.os.Build.VERSION.SDK_INT>=33?new Intent("android.provider.action.PICK_IMAGES"):new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE);pick.setType("image/*");try{startActivityForResult(pick,2);}catch(Exception e){status.setText("手机未提供照片选择器。");}});actions.addView(album,new LinearLayout.LayoutParams(0,64,1));Button back=new Button(this);back.setText("返回");back.setOnClickListener(v->finish());actions.addView(back,new LinearLayout.LayoutParams(0,64,1));root.addView(actions);setContentView(root);
        if(checkSelfPermission(android.Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{android.Manifest.permission.CAMERA},1);
    }
    private MultiFormatReader reader(){MultiFormatReader reader=new MultiFormatReader();EnumMap<DecodeHintType,Object> hints=new EnumMap<>(DecodeHintType.class);hints.put(DecodeHintType.POSSIBLE_FORMATS,Collections.singletonList(BarcodeFormat.QR_CODE));hints.put(DecodeHintType.TRY_HARDER,true);reader.setHints(hints);return reader;}
    private void start(){if(camera!=null||!surfaceReady||!foreground||finished||checkSelfPermission(android.Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)return;try{
        camera=Camera.open();Camera.Parameters params=camera.getParameters();if(params.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE))params.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);Camera.Size chosen=null;for(Camera.Size size:params.getSupportedPreviewSizes())if(size.width<=1280&&(chosen==null||size.width>chosen.width))chosen=size;if(chosen!=null)params.setPreviewSize(chosen.width,chosen.height);camera.setParameters(params);Camera.Size shape=params.getPreviewSize();previewHost.post(()->{float ratio=(float)shape.height/shape.width;int w=previewHost.getWidth(),h=previewHost.getHeight();if(w<=0||h<=0)return;if((float)w/h>ratio)w=Math.round(h*ratio);else h=Math.round(w/ratio);preview.setLayoutParams(new android.widget.FrameLayout.LayoutParams(w,h,Gravity.CENTER));});
        int rotation=getWindowManager().getDefaultDisplay().getRotation()*90;camera.setDisplayOrientation((90-rotation+360)%360);camera.setPreviewDisplay(preview.getHolder());camera.setPreviewCallback((bytes,source)->{if(decoding||finished||System.currentTimeMillis()-lastFrame<450)return;Camera.Size size=source.getParameters().getPreviewSize();byte[] frame=bytes.clone();decoding=true;lastFrame=System.currentTimeMillis();worker.execute(()->{try{PlanarYUVLuminanceSource luminance=new PlanarYUVLuminanceSource(frame,size.width,size.height,0,0,size.width,size.height,false);Result result=reader().decodeWithState(new BinaryBitmap(new HybridBinarizer(luminance)));complete(result.getText());}catch(Exception ignored){}finally{runOnUiThread(()->decoding=false);}});});camera.startPreview();status.setText("将二维码放入画面中");
    }catch(Exception e){stop();status.setText("相机暂不可用，可以从相册识别。");}}
    private void stop(){if(camera!=null){camera.setPreviewCallback(null);camera.stopPreview();camera.release();camera=null;}}
    private void complete(String value){runOnUiThread(()->{if(finished||!foreground)return;finished=true;stop();setResult(RESULT_OK,new Intent().putExtra("code",value));finish();});}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=2||result!=RESULT_OK||data==null||data.getData()==null)return;status.setText("正在识别…");worker.execute(()->{Bitmap bitmap=null;try{
        if(android.os.Build.VERSION.SDK_INT>=28)bitmap=ImageDecoder.decodeBitmap(ImageDecoder.createSource(getContentResolver(),data.getData()),(decoder,info,source)->{int w=info.getSize().getWidth(),h=info.getSize().getHeight();decoder.setAllocator(ImageDecoder.ALLOCATOR_SOFTWARE);decoder.setTargetSampleSize(Math.max(1,Math.max(w,h)/1800));});
        else {android.graphics.BitmapFactory.Options options=new android.graphics.BitmapFactory.Options();options.inJustDecodeBounds=true;try(java.io.InputStream in=getContentResolver().openInputStream(data.getData())){android.graphics.BitmapFactory.decodeStream(in,null,options);}options.inJustDecodeBounds=false;options.inSampleSize=Math.max(1,Math.max(options.outWidth,options.outHeight)/1800);try(java.io.InputStream in=getContentResolver().openInputStream(data.getData())){bitmap=android.graphics.BitmapFactory.decodeStream(in,null,options);}}
        if(bitmap==null)throw new IllegalStateException();int w=bitmap.getWidth(),h=bitmap.getHeight();int[] pixels=new int[w*h];bitmap.getPixels(pixels,0,w,0,0,w,h);Result code=reader().decodeWithState(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(w,h,pixels))));complete(code.getText());
    }catch(Exception e){runOnUiThread(()->status.setText("没有识别到二维码，请换一张清晰图片。"));}finally{if(bitmap!=null)bitmap.recycle();}});}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==1){if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)start();else status.setText("相机权限未开启，仍可从相册识别。");}}
    @Override protected void onResume(){super.onResume();foreground=true;start();}
    @Override protected void onPause(){foreground=false;stop();super.onPause();}
    @Override protected void onDestroy(){worker.shutdown();super.onDestroy();}
    @Override public void surfaceCreated(SurfaceHolder holder){surfaceReady=true;start();}
    @Override public void surfaceChanged(SurfaceHolder holder,int format,int w,int h){}
    @Override public void surfaceDestroyed(SurfaceHolder holder){surfaceReady=false;stop();}
}
