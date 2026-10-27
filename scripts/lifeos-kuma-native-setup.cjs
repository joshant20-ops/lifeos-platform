"use strict";
const fs = require("fs");
const { io } = require("socket.io-client");
const input=JSON.parse(fs.readFileSync(0,"utf8"));
const version=require("/app/package.json").version;
if(!/^1\.23\./.test(version)){process.stdout.write(JSON.stringify({ok:false,stage:"unsupported_version"}));process.exit(1);}
const socket=io("http://127.0.0.1:3001",{transports:["websocket"],reconnection:false,timeout:5000});
let monitors={};const beats=new Map();let stage="connect";let testID=null;
socket.on("monitorList",rows=>{monitors=rows;});
socket.on("heartbeat",beat=>{const id=Number(beat.monitorID);const list=beats.get(id)||[];if(!list.some(x=>x.time===beat.time)){list.push({time:beat.time,status:beat.status});beats.set(id,list.slice(-10));}});
const call=(event,...args)=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error("rpc_timeout")),12000);socket.emit(event,...args,res=>{clearTimeout(timer);resolve(res);});});
const checked=async(event,...args)=>{const res=await call(event,...args);if(!res||!res.ok)throw new Error("native_rpc_failed");return res;};
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const defaults={type:"http",name:"",parent:null,url:"https://",method:"GET",interval:60,retryInterval:60,resendInterval:0,maxretries:2,timeout:10,notificationIDList:{},ignoreTls:false,upsideDown:false,packetSize:56,expiryNotification:false,maxredirects:10,accepted_statuscodes:["200-299"],dns_resolve_type:"A",dns_resolve_server:"1.1.1.1",docker_container:"",docker_host:null,proxyId:null,mqttUsername:"",mqttPassword:"",mqttTopic:"",mqttSuccessMessage:"",authMethod:null,oauth_auth_method:"client_secret_basic",httpBodyEncoding:"json",kafkaProducerBrokers:[],kafkaProducerSaslOptions:{mechanism:"None"},kafkaProducerSsl:false,kafkaProducerAllowAutoTopicCreation:false,gamedigGivenPortOnly:true,active:true};
const waitFor=async(predicate,seconds)=>{const until=Date.now()+seconds*1000;while(Date.now()<until){if(predicate())return;await pause(1000);}throw new Error("heartbeat_timeout");};
const run=async()=>{
 await new Promise((resolve,reject)=>{socket.once("connect",resolve);socket.once("connect_error",()=>reject(new Error("connect_failed")));});
 stage="setup";const needed=await call("needSetup");
 if(needed===true)await checked("setup",input.username,input.password);
 else if(needed!==false)throw new Error("invalid_setup_state");
 stage="login";await checked("login",{username:input.username,password:input.password,token:""});
 await checked("getMonitorList");
 const owned=[];
 stage="monitors";
 for(const spec of input.monitors){
   const matches=Object.values(monitors).filter(m=>m.name===spec.name);
   if(matches.length>1)throw new Error("duplicate_managed_monitor");
   if(matches.length===1){
     if(Object.keys(spec).some(k=>String(matches[0][k])!==String(spec[k])))throw new Error("existing_monitor_changed");
     owned.push(Number(matches[0].id));continue;
   }
   const result=await checked("add",{...defaults,...spec});owned.push(Number(result.monitorID));
 }
 stage="live_heartbeats";
 await waitFor(()=>owned.every(id=>(beats.get(id)||[]).filter(b=>b.status===1).length>=2),160);
 stage="failure_recovery_test";
 const test={...defaults,name:"LifeOS temporary monitoring verification",type:"port",hostname:"127.0.0.1",port:1,maxretries:0};
 if(Object.values(monitors).some(m=>m.name===test.name))throw new Error("old_diagnostic_monitor_present");
 testID=Number((await checked("add",test)).monitorID);
 await waitFor(()=>(beats.get(testID)||[]).some(b=>b.status===0),75);
 await checked("editMonitor",{...test,id:testID,port:3001});
 await waitFor(()=>(beats.get(testID)||[]).some(b=>b.status===1),90);
 const history=await checked("getMonitorBeats",testID,1);
 if(!history.data.some(b=>b.status===0)||!history.data.some(b=>b.status===1))throw new Error("history_not_persisted");
 await checked("deleteMonitor",testID);testID=null;
 stage="complete";console.log(JSON.stringify({ok:true,version,configured:owned.length,healthy:owned.length,minimum_up_samples:2,failure_and_recovery_history:true,diagnostic_removed:true,notifications_configured:false}));
};
const watchdog=setTimeout(()=>{console.log(JSON.stringify({ok:false,stage:"overall_timeout"}));process.exit(1);},420000);
run().then(()=>{clearTimeout(watchdog);socket.close();}).catch(async()=>{if(testID!==null){try{await checked("deleteMonitor",testID);}catch{}}console.log(JSON.stringify({ok:false,stage}));clearTimeout(watchdog);socket.close();process.exitCode=1;});
