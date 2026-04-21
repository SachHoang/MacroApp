# Dua len GitHub an toan

## Khong nen dua len repo

- `build/`, `dist/`, `__pycache__/`
- `macro_steps.json`
- file `.env`, token, key, cookie, log ca nhan
- bat ky file nao chua duong dan may ban, tai khoan Windows, email that, hoac du lieu macro da ghi

## Ly do

Thu muc build cua PyInstaller co the chua duong dan tuyet doi nhu `C:\Users\TEN_BAN\...`, tu do lo username Windows va cau truc may cua ban.

## Cach day len GitHub an toan

1. Khoi tao git:

```powershell
git init
```

2. Dat danh tinh commit rieng cho repo nay, khong dung email ca nhan:

```powershell
git config user.name "ten-ban-muon-hien"
git config user.email "YOUR_GITHUB_USERNAME@users.noreply.github.com"
```

3. Kiem tra file sap duoc dua len:

```powershell
git add .
git status
```

4. Neu thay `build/`, `dist/`, `macro_steps.json`, `.env`, hoac file la thi dung lai va xoa khoi staging.

5. Commit:

```powershell
git commit -m "Initial commit"
```

## Khuyen nghi bao mat

- Tren GitHub, bat `Keep my email addresses private`.
- Dung avatar, ten hien thi, va username khong lien quan den danh tinh that neu can an danh.
- Neu can chia se file build, dung GitHub Releases hoac cloud drive rieng, khong commit `dist/` vao source repo.
- Neu da lo push nham secret, chi xoa file o commit moi la khong du. Can rotate secret va xoa khoi lich su git.

## File mau

Repo nay da co `macro_steps.example.json` de mo ta dinh dang du lieu ma khong can dua macro that cua ban len GitHub.
