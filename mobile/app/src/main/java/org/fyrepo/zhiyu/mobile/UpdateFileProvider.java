package org.fyrepo.zhiyu.mobile;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Grants the system installer read access to one verified APK, never other files. */
public final class UpdateFileProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File file(Uri uri) throws FileNotFoundException {
        if(!"content".equals(uri.getScheme()) || !(BuildConfig.APPLICATION_ID+".updates").equals(uri.getAuthority())
            || !"/latest.apk".equals(uri.getPath()) || uri.getQuery()!=null || uri.getFragment()!=null || getContext()==null)throw new FileNotFoundException();
        File file=new File(new File(getContext().getCacheDir(),"updates"),"latest.apk");
        if(!file.isFile())throw new FileNotFoundException();return file;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!"r".equals(mode))throw new FileNotFoundException();return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public String getType(Uri uri) { try {file(uri);return "application/vnd.android.package-archive";}catch(FileNotFoundException error){return null;} }
    @Override public Cursor query(Uri uri,String[] columns,String selection,String[] args,String order) {
        try {
            File file=file(uri);String[] requested=columns==null ? new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE} : columns;
            MatrixCursor result=new MatrixCursor(requested);Object[] row=new Object[requested.length];
            for(int i=0;i<requested.length;i++)row[i]=OpenableColumns.DISPLAY_NAME.equals(requested[i]) ? "Zhiyu-update.apk" : OpenableColumns.SIZE.equals(requested[i]) ? file.length() : null;
            result.addRow(row);return result;
        }catch(FileNotFoundException error){return null;}
    }
    @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    @Override public int delete(Uri uri,String selection,String[] args){throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String selection,String[] args){throw new UnsupportedOperationException();}
}
