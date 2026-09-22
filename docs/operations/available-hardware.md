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
| tower | Active | Tower PC | Intel Core i5-4690K @ 3.50 GHz | ~16 GB (confirm exact configuration) | NVIDIA P106-100 6 GB | TBD | LAN; current address 192.168.0.201 | Primary local/private AI compute host. Runs Tower Ollama; Engineer VM is associated with this host. |
| laptop-board-01 | Candidate / details required | Spare laptop motherboard | TBD | TBD | TBD | TBD | TBD | Physically available. Assess as a possible independent LifeOS inference/engineering worker once CPU, maximum/current RAM, GPU, storage interfaces, network interfaces and power requirements are identified. |

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
