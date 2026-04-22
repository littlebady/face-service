package com.example.checkinexcel.controller;

import com.example.checkinexcel.service.ExcelService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayOutputStream;

@RestController
@RequestMapping("/api/excel")
@CrossOrigin(origins = "*")  // 允许跨域，方便前端调用
public class ExcelController {

    @Autowired
    private ExcelService excelService;

    /**
     * 上传txt文件，返回生成的Excel文件
     */
    @PostMapping("/generate")
    public ResponseEntity<Resource> generateExcel(@RequestParam("file") MultipartFile file) {
        try {
            // 调用服务层生成Excel
            ByteArrayOutputStream excelStream = excelService.generateExcelFromTxt(file);

            // 生成文件名
            String originalFilename = file.getOriginalFilename();
            String excelFilename = excelService.generateExcelFilename(originalFilename);

            // 返回Excel文件
            ByteArrayResource resource = new ByteArrayResource(excelStream.toByteArray());

            return ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=\"" + excelFilename + "\"")
                    .contentType(MediaType.parseMediaType(
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
                    .body(resource);

        } catch (Exception e) {
            e.printStackTrace();
            return ResponseEntity.badRequest().build();
        }
    }
}
