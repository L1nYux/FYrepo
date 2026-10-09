'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
class AccountSnapshot{
  constructor(root){this.root=root;}
  file(origin){return path.join(this.root,crypto.createHash('sha256').update(origin).digest('hex')+'.json');}
  save(origin,value){
    if(!value.authenticated||!value.username)return this.remove(origin);
    const fields=['username','nickname','accountId','teamId','teamName','spaceId','spaceName','apiSpaceId','spaces','needsTeam','serverVersion','isAdmin','canManageApi','hasEmail','mustChangePassword','isPlatformAdmin','canManageAccounts','canManageAdmission'];
    const account={authenticated:true,protocol:1};for(const field of fields)if(value[field]!==undefined)account[field]=value[field];
    fs.mkdirSync(this.root,{recursive:true});const file=this.file(origin),temp=file+'.tmp';fs.writeFileSync(temp,JSON.stringify({origin,account}),{mode:0o600});fs.renameSync(temp,file);
  }
  read(origin){try{const raw=fs.readFileSync(this.file(origin),'utf8');if(raw.length>100000)return null;const value=JSON.parse(raw);return value.origin===origin&&value.account?.authenticated&&typeof value.account.username==='string'?value.account:null;}catch(_){return null;}}
  remove(origin){if(origin)fs.rmSync(this.file(origin),{force:true});}
}
module.exports={AccountSnapshot};
