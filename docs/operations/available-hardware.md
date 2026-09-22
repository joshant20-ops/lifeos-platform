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
| tower | Active | Gigabyte Z97P-D3 Tower / Proxmox host | Intel Core i5-4690K @ 3.50 GHz, 4C/4T, up to 3.9 GHz | **32 GB installed (31 GiB usable)**; DIMM layout/speed TBD | NVIDIA P106-100 **6 GB**, 120 W limit; Intel integrated graphics | 240 GB-class SATA SSD (CT240, 223.6 GiB usable) + 1 TB-class WDC SATA HDD (931.5 GiB) | Realtek RTL8111/8168/8411 Gigabit Ethernet; negotiated speed TBD | Debian 12 / Proxmox kernel 6.8.12-23-pve; VT-x/KVM. Tower address 192.168.0.201. Ollama 0.33.2 installed. Engineer VM associated with host. |
| laptop-board-01 | Candidate / details required | Spare laptop motherboard | TBD | TBD | TBD | TBD | TBD | Physically available. Assess as a possible independent LifeOS inference/engineering worker once CPU, maximum/current RAM, GPU, storage interfaces, network interfaces and power requirements are identified. |

## Tower measured details

Measured over SSH on 2026-09-22:

- Motherboard: Gigabyte Technology Co., Ltd. **Z97P-D3**.
- BIOS: American Megatrends Inc. **F8**, dated 2015-09-18.
- CPU: Intel Core i5-4690K, 4 cores / 4 threads, 3.50 GHz nominal, 3.90 GHz reported maximum.
- Virtualisation: Intel VT-x; `/dev/kvm` present.
- RAM: 32,724,744 kB reported by Linux (~31 GiB usable); DIMM population and speed still require DMI collection.
- GPU: NVIDIA P106-100 (GP106), 6144 MiB VRAM; NVIDIA driver 580.178.04; CUDA 13.0 reported by nvidia-smi; 120 W power limit.
- Storage: CT240 SATA solid-state disk, 223.6 GiB usable; WDC SATA rotational disk, 931.5 GiB; optical SATA device.
- Network controller: Realtek RTL8111/8168/8411 PCIe Gigabit Ethernet.
- Host OS: Debian GNU/Linux 12 (bookworm), Proxmox kernel 6.8.12-23-pve.
- Ollama: version 0.33.2 installed on Tower host. Installed model list still to be captured.

Still to establish: DIMM layout/speed/free slots, Engineer VM resource allocation, negotiated Ethernet speed, Ollama model/storage details, PSU, and physical GPU/case clearance.

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

## Change policy

Update this inventory whenever hardware becomes available, is removed, changes configuration, or is benchmarked. Record measured values rather than estimates where practical. Do not promote candidate hardware to Active solely because it can boot; establish its useful role and relevant performance first.
