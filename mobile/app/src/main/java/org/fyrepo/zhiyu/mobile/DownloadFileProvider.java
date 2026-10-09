package org.fyrepo.zhiyu.mobile;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Read-only grants for app downloads on Android 8 and 9. */
public final class DownloadFileProvider extends ContentProvider {
    public boolean onCreate(){return true;}
    private File file(Uri uri)throws FileNotFoundException{try{String name=uri.getLastPathSegment();if(name==null||!name.matches("[a-f0-9]{64}-[^/\\\\]+"))throw new IOException();File root=new File(getContext().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS),"知域").getCanonicalFile(),file=new File(root,name).getCanonicalFile();if(!root.equals(file.getParentFile())||!file.isFile())throw new IOException();return file;}catch(IOException e){throw new FileNotFoundException();}}
    public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{if(!"r".equals(mode))throw new FileNotFoundException();return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);}
    public String getType(Uri uri){String name=uri.getLastPathSegment(),suffix=name==null?"":name.substring(name.lastIndexOf('.')+1).toLowerCase();String mime=android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(suffix);return mime==null?"application/octet-stream":mime;}
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){try{File f=file(uri);MatrixCursor c=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});c.addRow(new Object[]{f.getName().substring(65),f.length()});return c;}catch(Exception e){return null;}}
    public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
}
