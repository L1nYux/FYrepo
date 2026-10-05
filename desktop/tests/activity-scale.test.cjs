const test=require('node:test'),assert=require('node:assert/strict');
const {level,percent}=require('../../static/aihub/activity-scale.js');
const {validateInfo}=require('../release-details.cjs');
test('activity shade advances each five percent and is darkest only at 25 percent',()=>{
 for(const [cost,shade] of [[0,0],[.1,1],[.99,1],[1,2],[2,3],[3,4],[4,5],[4.999,5],[5,6],[99,6]])assert.equal(level(cost,20),shade);
 assert.equal(level(.1007,20,22),1);assert.equal(percent(.1007,20),.5035);
});
test('unlimited or zero base allowance never creates a false percentage',()=>{
 assert.equal(percent(1,null),null);assert.equal(percent(1,0),null);assert.equal(level(1,null),1);assert.equal(level(0,20,5),1);
});
test('release metadata only permits known local feature routes and matching versions',()=>{
 const info=validateInfo({version:'0.2.12',features:[{title:'Valid',path:'/assistant/'},{title:'Bad',path:'https://evil.example/'},{title:'Bad',path:'/admin/'}]},'0.2.12');
 assert.equal(info.features.length,1);assert.throws(()=>validateInfo(info,'0.2.13'));
});
