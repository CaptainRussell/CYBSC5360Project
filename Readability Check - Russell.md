# Readability check: top-20 sentences (Results Section D)

For each sentence, judge whether it makes sense on its own, without the raw records.
Mark Yes or No in the last column and add a note if something reads badly.
The sentences are copied exactly from the saved reports (leads.csv); nothing is reworded.

## Project 2 (held-out test)

| Rank | File | Check | Sentence | Makes sense? |
|---|---|---|---|---|
| 1 | `white.zip › white.bmp` | C3 | This file is locked with a password. Nobody can read it without the password. | |
| 2 | `attr.html` | C1 | The name ends in “.html”, which means a web page, but the file is really a photo (JPEG). | |
| 2 | `attr.html` | C5 | It is the only photo among the 5 files in its folder. The others are mostly web pages, pictures and text files. | |
| 2 | `attr.html` | C6 | The guides and web pages on this drive mention 3 of the 4 other files in this folder by name, but never this one. | |
| 3 | `$IZB47AA.jpg` | F1 | Almost every file on this drive (4,564 of them) was last changed at the same moment, 2 Oct 2011, 11:57:01 AM, when they were copied together. This file was changed at a different time, 5 Oct 2011, 3:45:28 AM, along with only 0 other files. | |
| 4 | `tracking.log` | F1 | Almost every file on this drive (4,564 of them) was last changed at the same moment, 2 Oct 2011, 11:57:01 AM, when they were copied together. This file was changed at a different time, 5 Oct 2011, 1:59:05 AM, along with only 0 other files. | |
| 5 | `bx` | C4 | This is a Linux program, which should hold only computer code, yet it contains the plain sentence “Password is [$2]”. Someone may have hidden a password here. | |
| 6 | `white.zip` | C3 | Files inside this archive are locked with a password: white.bmp. | |
| 6 | `white.zip` | C7 | This archive is a bundle of files. Inside it are personal items: white.bmp (empty file, locked with a password). | |
| 7 | `$RZB47AA.jpg` | F1 | Almost every file on this drive (4,564 of them) was last changed at the same moment, 2 Oct 2011, 11:57:01 AM, when they were copied together. This file was changed at a different time, 5 Oct 2011, 4:10:00 AM, along with only 0 other files. | |
| 8 | `movie.eml` | C5 | It is the only email among the 34 files in its folder. The others are mostly pictures and text files. | |
| 8 | `movie.eml` | C6 | The guides and web pages on this drive mention 21 of the 33 other files in this folder by name, but never this one. | |
| 9 | `index.html` | C4 | This file contains the sentence “password is "cpre536at17F"”. It looks like a password someone wrote down. | |
| 10 | `mypuppy2.7z` | C1 | The name ends in “.7z”, which means a .7z file, but the file is really a RAR archive (a bundle of files). | |
| 11 | `gzip` | C5 | It is the only photo among the 89 files in its folder. The others are mostly Linux programs, text files and pictures. | |
| 12 | `digestcomps` | C5 | It is the only email among the 25 files in its folder. The others are mostly text files. | |
| 13 | `transactions_art_guide.pdf` | C3 | This file is locked with a password. Nobody can read it without the password. | |
| 13 | `transactions_art_guide.pdf` | C6 | The guides and web pages on this drive mention 3 of the 5 other files in this folder by name, but never this one. | |
| 14 | `favicons.sqlite` | C5 | At 5.0 MB it is about 25 times bigger than the other sqlite files in its folder, which are around 208 KB each. | |
| 15 | `places.sqlite` | C5 | At 5.0 MB it is about 25 times bigger than the other sqlite files in its folder, which are around 208 KB each. | |
| 16 | `muhammad-ali-draft2-grayscale.jpg` | C5 | At 571 KB it is about 19 times bigger than the other photos in its folder, which are around 29 KB each. | |
| 17 | `eclipse_update_120.jpg` | C5 | It is the only photo among the 5 files in its folder. The others are mostly data files and text files. | |
| 18 | `eclipse_update_120.jpg` | C5 | It is the only photo among the 5 files in its folder. The others are mostly data files and text files. | |
| 19 | `eclipse_update_120.jpg` | C5 | It is the only photo among the 5 files in its folder. The others are mostly data files and text files. | |
| 20 | `eclipse_update_120.jpg` | C5 | It is the only photo among the 5 files in its folder. The others are mostly data files and text files. | |

## Project 1 (development case)

| Rank | File | Check | Sentence | Makes sense? |
|---|---|---|---|---|
| 1 | `temp.gif` | C1 | The name ends in “.gif”, which means a GIF picture, but the file is really a password-locked Word, Excel or PowerPoint file. | |
| 1 | `temp.gif` | C3 | This file is locked with a password. Nobody can read it without the password. | |
| 1 | `temp.gif` | C5 | It is the only locked Office file among the 12 files in its folder. The others are mostly PDF documents, text files and ZIP archives. | |
| 2 | `Constants.java` | C4 | This file contains the sentence “secret is "QwF3p2Jir9oRt7b"”. It looks like a password someone wrote down. | |
| 2 | `Constants.java` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 3 | `Koala.jpg` | C2 | A photo should end after 763 KB, but the file keeps going for another 29 KB. That extra part is a hidden RAR archive (a bundle of files) holding JamesCooper.jpg. | |
| 3 | `Koala.jpg` | C5 | At 791 KB it is about 29 times bigger than the other photos in its folder, which are around 27 KB each. | |
| 3 | `Koala.jpg` | C6 | The guides and web pages on this drive mention 15 of the 15 other files in this folder by name, but never this one. | |
| 4 | `Manual.docx` | C3 | This file is locked with a password. Nobody can read it without the password. | |
| 4 | `Manual.docx` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 5 | `cref_t1.exe` | C4 | This is a Windows program, which should hold only computer code, yet it contains the plain sentence “pass is "kohaku123"”. Someone may have hidden a password here. | |
| 5 | `cref_t1.exe` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 6 | `ReadMe.txt` | C1 | The name ends in “.txt”, which means a text file, but the file is really a photo (JPEG). | |
| 7 | `ssh` | C4 | This is a Linux program, which should hold only computer code, yet it contains the plain sentence “secret is wannabeamillionaire”. Someone may have hidden a password here. | |
| 8 | `Sales.xls` | C3 | This file is locked with a password. Nobody can read it without the password. | |
| 9 | `applet.opt` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 10 | `build.xml` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 11 | `SamplePasswdBioApplet.java` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 12 | `biometry-client.expected.out` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 13 | `biometryEnroll.scr` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 14 | `biometryMatch.scr` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 15 | `readme.txt` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 16 | `hello_world.zip` | C7 | This archive is a bundle of files. Inside it are personal items: Sales.xls (spreadsheet, locked with a password) and hello.eml (email). | |
| 16 | `hello_world.zip` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 17 | `cref_tdual.exe` | F1 | Almost every file on this drive (2,224 of them) was last changed at the same moment, 6 Sep 2011, 3:21:58 AM, when they were copied together. This file was changed at a different time, 6 Sep 2011, 2:02:00 PM, along with only 11 other files. | |
| 18 | `package-list` | C6 | The guides and web pages on this drive mention 12 of the 12 other files in this folder by name, but never this one. | |
| 19 | `package-list` | C6 | The guides and web pages on this drive mention 12 of the 12 other files in this folder by name, but never this one. | |
| 20 | `package-list` | C6 | The guides and web pages on this drive mention 13 of the 13 other files in this folder by name, but never this one. | |
