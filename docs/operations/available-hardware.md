# Available Hardware Inventory

This document is the canonical inventory of hardware that is available or potentially available to LifeOS.

Its purpose is to support evidence-based decisions about local AI inference, engineering workers, storage, orchestration, and future hardware allocation. Hardware should not be assumed available unless it is recorded here as confirmed.

## Status definitions

- **Active** — installed and currently used by LifeOS.
- **Available** — known hardware available for allocation but not currently part of LifeOS.
- **Candidate / details required** — believed to be available, but specifications or condition still need to be established.
- **Reserved** — available hardware intentionally allocated to another purpose.

## Inventory

| ID | Status | Device | CPU | RAM | GPU / accelerator | Storage | Network | Current role / notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pi5-docker | Active | Raspberry Pi 5 | Raspberry Pi 5 SoC | 8 GB | — | 1 TB SSD | TBD | LifeOS orchestration/control host; hostname `Docker`. Local/private LLM inference must not run here. |
| pi5-spare | Available | Raspberry Pi 5 | Raspberry Pi 5 SoC | TBD | Hailo-8 AI HAT available for compatible inference workloads | TBD | TBD | Second Pi 5; available role TBD. Hailo-8 is not assumed to accelerate Ollama/LLM workloads. |
| pi3 | Available | Raspberry Pi 3 | TBD | TBD | — | TBD | TBD | Available role TBD. |
| pi1b-pool | Available | Several Raspberry Pi 1B boards | TBD | TBD | — | TBD | TBD | Quantity/spec revisions to confirm; available for lightweight infrastructure roles. |
| tower | Active | Gigabyte Z97P-D3 Tower / Proxmox host | Intel Core i5-4690K @ 3.50 GHz, 4C/4T, up to 3.9 GHz | **32 GB DDR3-1600 (31 GiB usable), platform maximum; 4×8 GB Samsung, all slots occupied** | NVIDIA P106-100 **6 GB**; current Qwen 7B inference verified **100% GPU**; Intel integrated graphics | 240 GB-class SATA SSD (CT240, 223.6 GiB usable) + 1 TB-class WDC SATA HDD (931.5 GiB) | Realtek RTL8111/8168/8411; **1 Gb/s full duplex verified** | Debian 12 / Proxmox. Tower address 192.168.0.201. Tower-host Ollama is the primary LifeOS local-AI endpoint and keeps the GPU under host control for shared/future workloads such as Immich. |
| engineer-vm | Active | Proxmox VM 102 `engineer` | 4 vCPU, host CPU type; exposes all 4 i5-4690K cores | **16 GB fixed**, ballooning disabled; 4 GB guest swap | No GPU passthrough by design | 100 GB virtual SCSI disk; ~72 GB free when measured | VirtIO via `vmbr0` | Debian 12; 192.168.0.204. Runs Engineer/OpenHands. Local Ollama 0.20.6 + Qwen2.5-Coder 7B provides local CPU fallback; primary inference is Tower-host Ollama. Starts automatically with Tower. |
| laptop-board-01 | Candidate / details required | Spare laptop motherboard | TBD | TBD | TBD | TBD | TBD | Physically available. Assess as a possible independent LifeOS inference/engineering worker once CPU, maximum/current RAM, GPU, storage interfaces, network interfaces and power requirements are identified. |

## Tower measured details

Measured over SSH on 2026-09-22:

- Motherboard: Gigabyte Technology Co., Ltd. **Z97P-D3**.
- BIOS: American Megatrends Inc. **F8**, dated 2015-09-18.
- CPU: Intel Core i5-4690K, 4 cores / 4 threads, 3.50 GHz nominal, 3.90 GHz reported maximum.
- Virtualisation: Intel VT-x; `/dev/kvm` present.
- RAM: **32 GB maximum and installed**. Four 8 GB Samsung `M378B1G73DB0-CK0` dual-rank DDR3 DIMMs, all four slots populated, 1600 MT/s configured speed.
- GPU: NVIDIA P106-100 (GP106), 6144 MiB VRAM; NVIDIA driver 580.178.04; CUDA 13.0 reported by `nvidia-smi`; 120 W power limit.
- Storage: CT240 SATA solid-state disk, 223.6 GiB usable; WDC SATA rotational disk, 931.5 GiB; optical SATA device.
- Network: Realtek RTL8111/8168/8411 PCIe Gigabit Ethernet; **1000 Mb/s, full duplex** measured on `enp3s0`.
- Host OS: Debian GNU/Linux 12 (bookworm), Proxmox kernel 6.8.12-23-pve.
- Ollama: **0.33.2** on Tower host. Installed models: `qwen2.5-coder:7b-instruct` (4.7 GB) and `qwen2.5-coder:1.5b` (986 MB).
- Effective Ollama service configuration: `CUDA_VISIBLE_DEVICES=0`, `OLLAMA_VULKAN=0`, `OLLAMA_HOST=0.0.0.0:11434`, `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_CONTEXT_LENGTH=8192`.
- Runtime verification: `qwen2.5-coder:7b-instruct` loads at approximately **5.0 GB, 100% GPU, context 8192** according to `ollama ps`.
- GPU allocation principle: the P106 is deliberately **not PCIe-passed through to Engineer**. Tower-host Ollama is the primary GPU inference service, preserving host-level control for future shared GPU workloads such as Immich.

## Engineer VM measured details

Measured on 2026-09-22:

- Proxmox VM ID: **102**, name `engineer`.
- CPU: 4 vCPU, `cpu: host`, one socket; guest reports i5-4690K and all four cores.
- RAM: **16384 MB fixed**, ballooning disabled; guest reports ~15 GiB usable plus 4 GiB swap.
- Disk: 100 GB VirtIO-SCSI virtual disk; guest ext4 root had ~72 GB free when measured.
- Network: VirtIO bridged through `vmbr0`.
- Boot: `onboot: 1`; startup order 1 with 30-second delay.
- GPU: no PCI GPU exposed to guest, intentionally.
- Ollama: **0.20.6**, active as a local service. Installed model: `qwen2.5-coder:7b-instruct`; model data ~4.4 GB.
- LifeOS endpoint policy on Engineer: primary `http://192.168.0.201:11434`; fallback `http://127.0.0.1:11434`; model `qwen2.5-coder:7b-instruct`.
- Existing Paperless classification evidence records successful use of backend `towerpc` at the primary Tower endpoint.
- Role: Engineer/OpenHands execution VM with CPU-local Ollama fallback; normal local GPU inference is provided by Tower-host Ollama.

Still to establish for the physical Tower where useful: PSU make/model/wattage, physical case/GPU clearance, sustained inference thermals/power, and measured OpenHands workload throughput.

## Candidate hardware assessment

Before adding candidate hardware to the active pool, record where applicable:

- manufacturer and exact model / motherboard identifier;
- CPU model, core/thread count and instruction-set support;
- installed RAM and maximum supported RAM;
- RAM type, speed and available slots;
- discrete/integrated GPU and usable VRAM;
- storage interfaces and installed storage;
- Ethernet/Wi-Fi capabilities;
- measured idle and sustained-load power;
- cooling condition and sustained thermals;
- operating-system/virtualisation compatibility;
- Wake-on-LAN or other remote power-control capability;
- measured local-LLM throughput for candidate models;
- stability under sustained inference;
- intended LifeOS role.

## Architecture principle

Prefer **job-level distribution** across independent workers over splitting a single LLM across heterogeneous machines unless measurements demonstrate a clear advantage for distributed inference.

Governor should remain responsible for policy/routing and machine lifecycle. OpenHands remains responsible for repository engineering. Private/local-only workloads must remain on permitted local hardware.

For the current Tower architecture, keep GPU ownership at the Proxmox host unless measurements and a deliberate architecture change justify otherwise. Tower-host Ollama is the primary GPU-backed LifeOS inference service; Engineer-local Ollama is a fallback rather than the normal GPU path.

## Change policy

Update this inventory whenever hardware becomes available, is removed, changes configuration, or is benchmarked. Record measured values rather than estimates where practical. Do not promote candidate hardware to Active solely because it can boot; establish its useful role and relevant performance first.
