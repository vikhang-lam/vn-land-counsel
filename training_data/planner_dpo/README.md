# PLANNER DPO DATASET

## Muc tieu

Bo du lieu nay dung de DPO Planner Qwen3-8B da qua SFT. Muc tieu la giup Planner
dung dung thuat ngu phap ly, quan he phap ly, `issue_type`, `target_kind`,
`time_basis`, fact lien quan va y dinh retrieval query tren nhieu nhom bai toan
dat dai. Dataset khong day Planner tra loi noi dung dieu luat va khong dua
Dieu/Khoan/Diem vao output Planner.

Quy mo v1 duoc khoa tai 2.000 preference pairs:

- 1.600 train.
- 200 validation.
- 200 test doc lap.
- 40 batch, moi batch 50 record.

## Contract production duoc pin

Moi record dung dung transport production:

```text
CAU HOI:
<question>

CASE_FACTS:
- F001 [CATEGORY]: <value>

TEMPORAL_CONTEXT:
<verified JSON from Temporal Extractor>
```

System prompt khong lap lai trong tung review record. Builder phai doc
`DECOMPOSE_PROMPT` tu `core/prompts/planning/__init__.py`, kiem tra SHA-256
`5ccd75b346ce8448884afaa4d524fd0837e5269c17d2baa45bd25d33f200e90a`,
roi moi inject prompt vao JSONL train.

`chosen` va `rejected` deu phai la plan hop JSON schema va contract cau truc. DPO
khong duoc hoc shortcut tu JSON hong, ID sai, thieu field hoac query vuot
contract. `chosen` phai dat day du semantic contract production; `rejected`
phai vi pham dung family ngu nghia da khai bao va khong mang them loi family
khac. Vi du temporal context khong co moc giao dich thi rejected co the gan
`giao_dich` de tao hard negative, trong khi chosen bat buoc giu `hien_hanh`.

## Python so huu ID

Review record chi dung hai khoa can bo cuc bo:

- `issue_key`, vi du `ISSUE_TRANSFER`.
- `requirement_key`, vi du `REQ_TRANSFER_FORM`.

Hai khoa nay chi dung de can chinh chosen/rejected va khai bao dependency. Khi
compile, Python phai:

1. Gan `I001`, `I002`, `I003` theo thu tu issue cua tung nhanh.
2. Gan `R001_01`, `R001_02` theo issue va thu tu requirement.
3. Doi `depends_on_keys` thanh canonical issue IDs cua cung nhanh.
4. Tu choi key trung, dependency tu tham chieu, dependency tro den issue sau
   hoac key khong ton tai.
5. Chi cho phep `fact_ids` co trong `input.fact_ledger` va cam fact co category
   `REQUEST`.
6. Gan DPO pair ID theo thu tu batch; annotator khong tu tao pair ID.

Khong dua canonical `issue_id` hoac `requirement_id` vao review record. Dieu nay
ngan model nho bi thuong/phat chi vi gan sai ID vi tri trong qua trinh tao data.

## Cau truc review record

Schema chinh thuc nam tai `planner_dpo_record.schema.json`.

```yaml
version: 1
batch_id: batch_001
source_case_id: scale2_medium_196
split: train
difficulty: MEDIUM
primary_topic: LAND_USE
secondary_domains: [FORESTRY]

input:
  question: "..."
  fact_ledger:
    - fact_id: F001
      category: CONDUCT
      value: "..."
      source_quote: "..."
  temporal_context:
    giao_dich: null
    vi_pham: null
    van_ban_dich_danh: null

chosen:
  issues:
    - issue_key: ISSUE_A
      issue: "..."
      issue_type: AUTHORITY_PROCEDURE
      depends_on_keys: []
      time_basis: hien_hanh
      required_evidence:
        - requirement_key: REQ_A1
          target_kind: CONDUCT_CLASSIFICATION
          objective: "..."
          fact_ids: [F001]
          query: "..."

rejected:
  issues:
    - issue_key: ISSUE_A
      issue: "..."
      issue_type: AUTHORITY_PROCEDURE
      depends_on_keys: []
      time_basis: hien_hanh
      required_evidence:
        - requirement_key: REQ_A1
          target_kind: LEGAL_CONSEQUENCE
          objective: "..."
          fact_ids: [F001]
          query: "..."

preference:
  family: TERM_TARGET_BOUNDARY
  subtype: TARGET_KIND
  changed_paths: [/issues/0/required_evidence/0/target_kind]
  rejected_origin: RUNTIME_PLANNER_8B
  minimal_contrast: true
  gold_preference: CHOSEN
  rationale: "Rejected bien cau hoi phan loai hanh vi thanh tim he qua phap ly."

review:
  status: GOLD_REVIEWED
  reviewer: GPT-5.6 Sol
  reviewed_at: "2026-08-13T00:00:00Z"
  notes: ""
```

## Tam family mutation

Moi pair co dung mot family chinh. Neu mot output co nhieu loi, tach thanh cac
pair doc lap hoac chi giu contrast nho nhat quyet dinh preference.

1. `TERM_TARGET_BOUNDARY` - phan biet `target_kind` hoac `issue_type` de nham.
2. `LEGAL_RELATION_FRAMING` - sua chu the, hanh vi, doi tuong va quan he trung
   tam bi dong khung sai.
3. `QUERY_SEMANTIC_ALIGNMENT` - query phai giu dung target va quan he cua
   requirement, khong chi gan tu khoa.
4. `COVERAGE_DECOMPOSITION` - tach/gop issue va requirement dung cac ket qua
   nguoi dung hoi, khong bo sot quan he trong yeu.
5. `FACT_STATUS_GROUNDING` - lien ket dung fact lam thay doi quy pham va khong
   bien im lang thanh trang thai da/chua xay ra.
6. `TEMPORAL_VERSION_INTENT` - phan biet giao dich, vi pham, hien hanh va van
   ban dich danh theo Temporal Context.
7. `DEPENDENCY_SEQUENCE` - dependency chi tro den issue truoc va phan anh dung
   quan he tien quyet.
8. `CROSS_DOMAIN_BOUNDARY` - giu land anchor khi vu viec lien quan dan su,
   ngan hang, xay dung, lam nghiep, hon nhan, thua ke hoac to tung.

Quota family va topic duoc khoa trong `planner_dpo_manifest.json`.

## Nguon chosen va rejected

Thu tu uu tien rejected:

1. Output that cua `Planner-Qwen3-8B-LoRA` sai nhung van hop schema.
2. Output Qwen3-8B base co near-miss phap ly.
3. Counterfactual toi thieu, chi sua mot family loi.
4. Historical trace hoac hard negative do reviewer viet khi khong co output that.

Chosen co the bat dau tu Planner Gold, nhung reviewer phai doi chieu lai contract
production va y nghia phap ly. Khong xem exact string match la tieu chuan dung;
nhieu query khac chu van co the cung hop le.

Rejected khong duoc:

- Sai JSON hoac sai schema.
- Chi sai canonical ID vi tri.
- Khac chosen chi o dau cau, chinh ta hoac cach viet tuong duong.
- Dua dap an Dieu/Khoan/Diem vao query.
- Chua nhieu family loi khong tach duoc tin hieu preference.
- Khac chosen ve do dai qua lon den muc model hoc shortcut.

## Invariant builder bat buoc

JSON Schema chi kiem tra hinh dang. Builder van phai kiem tra cac quan he sau:

- Moi batch co dung 50 source cases va khong trung `source_case_id`.
- Tat ca pair cung `source_case_id` nam trong mot split; v1 cho toi da mot pair
  tren moi source case.
- Train/val giu split Planner goc. Test dung case raw withheld, khong nam trong
  Planner Gold hoac bo Planner test da mo truoc day.
- `source_quote` phai nam nguyen van trong question theo contract Fact Gold.
- Chosen/rejected co 1-3 issues; moi issue co 1-2 requirements.
- `issue_key` va `requirement_key` khong trung trong tung nhanh.
- Moi `depends_on_keys` tro den issue xuat hien truoc trong cung nhanh.
- Objective co 8-24 tu.
- Query co 8-35 tu, toi da 220 ky tu; muc an toan la 18-25 tu.
- Query khong trung trong cung plan.
- `fact_ids` co 1-6 phan tu, co trong ledger va khong tro den `REQUEST`.
- Khong khang dinh trang thai dang ky, sang ten, cap phep, thanh toan hoac hoan
  tat neu ledger khong co fact xac nhan.
- Chosen va rejected deu qua Planner JSON schema sau khi Python gan canonical ID.
- Chosen phai tot hon rejected dung theo `family`, `subtype`, `changed_paths` va
  `rationale`; khong chi tot hon ve van phong.
- Khong co Dieu/Khoan/Diem hoac dap an phap luat trong issue, objective hay query.
- Tong quota split, topic, difficulty va family phai khop manifest truoc compile.

## JSONL DPO sau compile

Builder xuat conversational preference format:

```json
{
  "prompt": [
    {"role": "system", "content": "<pinned DECOMPOSE_PROMPT>"},
    {"role": "user", "content": "<production Planner transport>"}
  ],
  "chosen": [
    {"role": "assistant", "content": "{\"issues\":[...]}"}
  ],
  "rejected": [
    {"role": "assistant", "content": "{\"issues\":[...]}"}
  ],
  "metadata": {
    "pair_id": "PLDPO_000001",
    "source_case_id": "scale2_medium_196",
    "split": "train",
    "preference_family": "TERM_TARGET_BOUNDARY",
    "prompt_contract_version": 2,
    "system_prompt_sha256": "5ccd75b346ce8448884afaa4d524fd0837e5269c17d2baa45bd25d33f200e90a"
  }
}
```

Thinking phai tat khi render chat template, giong Planner SFT hien tai.
