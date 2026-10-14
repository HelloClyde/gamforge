"""Map device GBK absolute paths into an ASCII-only temporary host sandbox."""

SAVE_HOST_FS = r"""
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#endif
static int save_host_blocked;
static const char *save_host_path(const char *path){
 static char result[768];unsigned n=0,i=3;
 assert(path[0]=='A'&&path[1]==':'&&path[2]=='\\');
 /* Percent-encode GBK pairs, including trail bytes equal to backslash.
    Host fopen never has to interpret a device codepage. */
 const char hex[]="0123456789ABCDEF";
 while(path[i]){
  unsigned char b=(unsigned char)path[i++];
  if(b>=0x81&&path[i]){
   for(unsigned k=0;k<2;++k){
    if(k)b=(unsigned char)path[i++];
    result[n++]='%';result[n++]=hex[b>>4];result[n++]=hex[b&15];
   }
  }else result[n++]=b=='\\'?'/':b;
  assert(n+7<sizeof(result));
 }
 result[n]=0;return result;
}
static FILE *save_host_open(const char *path,const char *mode){
 if(save_host_blocked)return NULL;
 return fopen(save_host_path(path),mode);
}
static int save_host_mkdir(const char *path){
 if(save_host_blocked)return -1;
#ifdef _WIN32
 return _mkdir(save_host_path(path));
#else
 return mkdir(save_host_path(path),0700);
#endif
}
#define fs_fopen save_host_open
#define fs_mkdir save_host_mkdir
#define fs_fread fread
#define fs_fwrite fwrite
#define fs_fseek fseek
#define fs_ftell ftell
#define fs_fclose fclose
#define fs_update fflush
#define fs_remove(p) remove(save_host_path(p))
"""
