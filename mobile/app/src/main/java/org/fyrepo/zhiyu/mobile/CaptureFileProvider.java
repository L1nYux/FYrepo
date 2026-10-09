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

/** URI grants expose only one UUID-named temporary photo, never a directory. */
public final class CaptureFileProvider extends ContentProvider {
    @Override public boolean onCreate(){return true;}
    private File file(Uri uri) throws FileNotFoundException {
        String name=uri.getLastPathSegment();
        if(name==null||!name.matches("[0-9a-f-]{36}\\.jpg")||uri.getPathSegments().size()!=1)throw new FileNotFoundException();
        return new File(new File(getContext().getCacheDir(),"captures"),name);
    }
    @Override public String getType(Uri uri){return "image/jpeg";}
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!mode.equals("r")&&!mode.equals("w")&&!mode.equals("rw")&&!mode.equals("wt"))throw new FileNotFoundException();
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.parseMode(mode));
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
        MatrixCursor out=new MatrixCursor(projection==null?new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE}:projection);
        try {File f=file(uri);Object[] values=new Object[out.getColumnCount()];for(int i=0;i<values.length;i++)values[i]=out.getColumnNames()[i].equals(OpenableColumns.DISPLAY_NAME)?f.getName():out.getColumnNames()[i].equals(OpenableColumns.SIZE)?f.length():null;out.addRow(values);}catch(Exception ignored){}
        return out;
    }
    @Override public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
    @Override public int delete(Uri uri,String selection,String[] args){throw new UnsupportedOperationException();}
    @Override public int update(Uri uri,ContentValues values,String selection,String[] args){throw new UnsupportedOperationException();}
}
