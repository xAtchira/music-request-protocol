# 🎵 Music Request Server

- [ดาวน์โหลดเอกสาร (PDF)](./6710451534_MRP.pdf)
- [ลิงค์ Video](https://youtube.com)

โปรแกรม **Network Application** สำหรับให้ผู้ใช้งานสามารถติดต่อกับ **Music Server** ผ่านเครือข่าย เพื่อเรียกดู ค้นหา ดูรายละเอียด และดาวน์โหลดไฟล์เพลงจาก Server

โปรแกรมพัฒนาด้วยแนวคิด **Client-Server Architecture** โดยใช้ **TCP Socket** ในการสื่อสาร และมีการออกแบบ **Application-Layer Protocol** ขึ้นมาเองในชื่อ **MRP (Music Request Protocol)**

---

## 📌 ภาพรวม Project

ระบบประกอบด้วย 2 ส่วนหลัก ได้แก่

- **Client** — ทำหน้าที่เป็นส่วนติดต่อกับผู้ใช้งาน และส่ง `Request` ไปยัง Server
- **Server** — ทำหน้าที่จัดการข้อมูลเพลง ประมวลผล `Request` และส่ง `Response` กลับไปยัง Client

การสื่อสารระหว่าง Client และ Server ใช้ **MRP over TCP**

```text
┌─────────────────────┐
│    Music Client     │
│    Desktop GUI      │
└──────────┬──────────┘
           │
           │ MRP over TCP
           │
           ▼
┌─────────────────────┐
│    Music Server     │
│                     │
│  MRP Request Handler│
└──────────┬──────────┘
           │
      ┌────┴─────┐
      ▼          ▼
 music_data   music/
   .json       files
```
# ✨ ความสามารถของโปรแกรม

 โปรแกรมรองรับการทำงานหลักดังนี้

- 📋 เรียกดูรายการเพลงทั้งหมด
- 🔍 ค้นหาเพลงจาก Keyword
- 🎵 ดูรายละเอียดของเพลง
- ⬇️ ดาวน์โหลดไฟล์เพลงจาก Server
- 📡 รับส่งข้อมูลผ่าน TCP Socket
- 🔄 สื่อสารระหว่าง Client และ Server ด้วย MRP
- 📊 แสดง Status Code และ Status Phrase
- ❌ รองรับการจัดการ Error จาก Request ที่ไม่ถูกต้อง

# 🛠️ เทคโนโลยีที่ใช้
- Programming Language: Python
- Network: TCP Socket
- Application-Layer Protocol: MRP v1.0
- GUI: PySide6 / Tkinter
- Data Storage: JSON
- File Storage: Local File System

# 📡 MRP — Music Request Protocol

MRP (Music Request Protocol) คือ Application-Layer Protocol ที่ออกแบบขึ้นสำหรับใช้ในการสื่อสารระหว่าง Client และ Server ของโปรแกรมนี้

MRP ใช้รูปแบบการสื่อสารแบบ Request-Response
```text
Client                         Server
  │                              │
  │────── MRP Request ──────────>│
  │                              │
  │<───── MRP Response ──────────│
  │                              │
```
### คำสั่งที่รองรับ

| Command | รายละเอียด |
| :--- | :--- |
| `LIST` | ขอรายการเพลงทั้งหมด |
| `SEARCH <keyword>` | ค้นหาเพลงจาก Keyword |
| `INFO <song_id>` | ขอรายละเอียดของเพลง |
| `DOWNLOAD <song_id>` | ขอดาวน์โหลดไฟล์เพลง |
| `QUIT` | ยุติการเชื่อมต่อ |

ตัวอย่างการสื่อสาร

Client ส่ง `Request`
```text
SEARCH Believer
```
Server ส่ง `Response`
```text
200 OK
```
พร้อมข้อมูลเพลงที่ค้นพบ

# 📊 Status Code

MRP กำหนด Status Code สำหรับใช้แสดงผลลัพธ์ของการประมวลผล Request
| Status Code | Status Phrase        | ความหมาย                          |
| ----------- | -------------------- | --------------------------------- |
| `200`       | `OK`                 | Request สำเร็จ                    |
| `400`       | `BAD REQUEST`        | Request หรือ Parameter ไม่ถูกต้อง |
| `404`       | `NOT FOUND`          | ไม่พบเพลงหรือไฟล์ที่ร้องขอ        |
| `405`       | `METHOD NOT ALLOWED` | ไม่รองรับ Command ที่ร้องขอ       |
| `500`       | `SERVER ERROR`       | เกิดข้อผิดพลาดภายใน Server        |

# 📁 โครงสร้าง Project
```text
music-request-server/
│
├── client.py  
|
├── gui_client.py
│
├── server.py
│
├── protocol.py
│
├── music_data.json
│
├── music/
|   ├── song1.mp3
|   ├── song2.mp3
|
└── README.md
```

# 🚀 วิธีการติดตั้งและใช้งาน
1. Clone Repository
```bash
git clone <repository-url>
cd music-request-server
```
2. เริ่มต้น Server
```bash
python server/server.py
```
จากนั้น Server จะเปิด `TCP Socket` และรอรับการเชื่อมต่อจาก Client

3. เริ่มต้น Client

เปิด Terminal อีกหน้าต่างหนึ่ง แล้วใช้คำสั่ง
```bash
python server/gui_client.py
```
จากนั้น Client จะเชื่อมต่อไปยัง Music Server และแสดง GUI สำหรับใช้งาน

# 🎓 วัตถุประสงค์ของโครงการ

โครงการนี้จัดทำขึ้นเพื่อศึกษาและประยุกต์ใช้แนวคิดเกี่ยวกับ Socket Programming และ Computer Network โดยเน้นการทำงานของ

- Client-Server Architecture
- TCP Socket Programming
- Application-Layer Protocol Design
- Request-Response Communication
- Status Code และ Error Handling
- File Transfer ผ่าน TCP

# 👨‍💻 ผู้จัดทำ

### อัจชิระ แผ่นสุวรรณ์ 6710451534