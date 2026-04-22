package com.example.checkinexcel.service;

import org.apache.poi.ss.usermodel.*;
import org.apache.poi.ss.util.CellRangeAddress;
import org.apache.poi.xddf.usermodel.PresetColor;
import org.apache.poi.xddf.usermodel.XDDFColor;
import org.apache.poi.xddf.usermodel.XDDFSolidFillProperties;
import org.apache.poi.xddf.usermodel.chart.*;
import org.apache.poi.xssf.usermodel.*;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

@Service
public class ExcelService {

    /** 新格式中，明确为整型列的列名集合（short_answer_question 因有同名列需特殊处理，不放入此集合） */
    private static final Set<String> INTEGER_COLUMN_NAMES = Set.of(
            "total_checkin", "revoked_checkin", "choice_question"
    );

    /**
     * 从上传的txt文件生成Excel（兼容新旧两种格式）
     */
    public ByteArrayOutputStream generateExcelFromTxt(MultipartFile file) throws Exception {
        // 1. 创建工作簿和样式
        XSSFWorkbook workbook = new XSSFWorkbook();
        XSSFSheet sheet = workbook.createSheet("签到情况表");
        CellStyle cellStyle = createOrangeCellStyle(workbook);

        // 2. 读取txt文件内容
        List<String> lines = readTxtLines(file);
        if (lines.isEmpty()) {
            return writeToOutputStream(workbook);
        }

        // 3. 检测格式并处理数据
        boolean newFormat = isNewFormat(lines.get(0));

        int totalColIndex;
        if (newFormat) {
            totalColIndex = processNewFormat(sheet, lines, cellStyle);
        } else {
            totalColIndex = processOldFormat(sheet, lines, cellStyle);
        }

        // 4. 生成图表
        int rowcount = lines.size() - 1;
        createChart(sheet, rowcount, totalColIndex);

        // 5. 输出到字节流
        return writeToOutputStream(workbook);
    }

    // ===================== 格式检测 =====================

    /**
     * 检测是否为新格式：表头包含 total_checkin 列名
     * <p>
     * 旧格式表头不含 "total_checkin"，新格式表头含 "total_checkin"
     */
    private boolean isNewFormat(String headerLine) {
        return headerLine.contains("total_checkin");
    }

    // ===================== 旧格式处理 =====================

    /**
     * 处理旧格式：移除前两列，"总计"为最后一列
     *
     * @return "总计"列的索引（用于图表数据源）
     */
    private int processOldFormat(XSSFSheet sheet, List<String> lines, CellStyle cellStyle) {
        // 处理表头
        List<String> headerCells = parseLineRemoveFirstTwo(lines.get(0));
        customizeOldHeaderCells(headerCells);
        createHeaderRow(sheet, headerCells);

        // 处理数据行
        for (int i = 1; i < lines.size(); i++) {
            List<String> dataCells = parseLineRemoveFirstTwo(lines.get(i));
            createOldDataRow(sheet, i, dataCells, cellStyle);
        }

        // 旧格式 "总计" 一定是最后一列
        return headerCells.size() - 1;
    }

    /**
     * 旧格式表头定制：学号、姓名、总计
     */
    private void customizeOldHeaderCells(List<String> headerCells) {
        headerCells.set(0, "学号");
        headerCells.set(1, "姓名");
        headerCells.set(headerCells.size() - 1, "总计");
    }

    /**
     * 旧格式数据行：普通列为字符串，"总计"列为整数
     */
    private void createOldDataRow(XSSFSheet sheet, int rowIndex, List<String> cells, CellStyle cellStyle) {
        Row dataRow = sheet.createRow(rowIndex);

        // 普通列：字符串类型，值为"0"时标橙色
        for (int j = 0; j < cells.size() - 1; j++) {
            Cell cell = dataRow.createCell(j);
            cell.setCellValue(cells.get(j));
            if ("0".equals(cells.get(j))) {
                cell.setCellStyle(cellStyle);
            }
        }

        // "总计"列：整数类型
        Cell totalCell = dataRow.createCell(cells.size() - 1);
        totalCell.setCellValue(Integer.parseInt(cells.get(cells.size() - 1)));
        if ("0".equals(cells.get(cells.size() - 1))) {
            totalCell.setCellStyle(cellStyle);
        }
    }

    // ===================== 新格式处理 =====================

    /**
     * 处理新格式：不移除前两列，含 total_checkin 及额外4列
     *
     * @return "total_checkin"列的索引（用于图表数据源）
     */
    private int processNewFormat(XSSFSheet sheet, List<String> lines, CellStyle cellStyle) {
        // 处理表头
        List<String> headerCells = parseLineKeepAll(lines.get(0));
        customizeNewHeaderCells(headerCells);
        boolean[] integerCols = determineIntegerColumns(headerCells);
        createHeaderRow(sheet, headerCells);

        // 处理数据行
        for (int i = 1; i < lines.size(); i++) {
            List<String> dataCells = parseLineKeepAll(lines.get(i));
            createNewDataRow(sheet, i, dataCells, cellStyle, integerCols);
        }

        // 查找 total_checkin 列索引，用于图表
        int totalIdx = findColumnIndex(headerCells, "total_checkin");
        if (totalIdx < 0) {
            throw new IllegalArgumentException("新格式中未找到 total_checkin 列");
        }
        return totalIdx;
    }

    /**
     * 新格式表头定制：学号、姓名（其他列名保留原样）
     */
    private void customizeNewHeaderCells(List<String> headerCells) {
        headerCells.set(0, "学号");
        headerCells.set(1, "姓名");
        // total_checkin、revoked_checkin、choice_question、short_answer_question 等列名保留原样
    }

    /**
     * 根据表头判断每列的数据类型
     * <p>
     * 规则：
     * - total_checkin / revoked_checkin / choice_question → 整型
     * - short_answer_question 第一次出现 → 整型，后续出现 → 字符串型
     * - 其他列 → 字符串型
     */
    private boolean[] determineIntegerColumns(List<String> headers) {
        boolean[] isInteger = new boolean[headers.size()];
        int shortAnswerCount = 0;
        for (int i = 0; i < headers.size(); i++) {
            String header = headers.get(i);
            if (INTEGER_COLUMN_NAMES.contains(header)) {
                isInteger[i] = true;
            } else if ("short_answer_question".equals(header)) {
                shortAnswerCount++;
                // 只有第一个 short_answer_question 为整型
                if (shortAnswerCount == 1) {
                    isInteger[i] = true;
                }
                // 第二个及之后的 short_answer_question 为字符串型，不标记
            }
        }
        return isInteger;
    }

    /**
     * 新格式数据行：根据列类型决定存储方式
     * <p>
     * 整型列 → Integer.parseInt()，存为数字；字符串列 → 存为文本。
     * 所有列值为 "0" 时标橙色。
     */
    private void createNewDataRow(XSSFSheet sheet, int rowIndex, List<String> cells,
                                  CellStyle cellStyle, boolean[] integerCols) {
        Row dataRow = sheet.createRow(rowIndex);
        for (int j = 0; j < cells.size(); j++) {
            Cell cell = dataRow.createCell(j);
            if (integerCols[j]) {
                // 整型列：存为数字
                cell.setCellValue(Integer.parseInt(cells.get(j)));
            } else {
                // 字符串列：存为文本
                cell.setCellValue(cells.get(j));
            }
            // 值为"0"时标橙色（与原有逻辑一致）
            if ("0".equals(cells.get(j))) {
                cell.setCellStyle(cellStyle);
            }
        }
    }

    /**
     * 查找指定列名的列索引
     */
    private int findColumnIndex(List<String> headers, String columnName) {
        for (int i = 0; i < headers.size(); i++) {
            if (columnName.equals(headers.get(i))) {
                return i;
            }
        }
        return -1;
    }

    // ===================== 公共基础方法 =====================

    /**
     * 创建橙色背景样式
     */
    private CellStyle createOrangeCellStyle(XSSFWorkbook workbook) {
        CellStyle cellStyle = workbook.createCellStyle();
        cellStyle.setFillForegroundColor(IndexedColors.ORANGE.getIndex());
        cellStyle.setFillPattern(FillPatternType.SOLID_FOREGROUND);
        return cellStyle;
    }

    /**
     * 读取txt文件所有行
     */
    private List<String> readTxtLines(MultipartFile file) throws IOException {
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(file.getInputStream(), "UTF-8"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                lines.add(line);
            }
        }
        return lines;
    }

    /**
     * 解析一行txt内容：按双制表符分割，并移除前两列（旧格式）
     */
    private List<String> parseLineRemoveFirstTwo(String line) {
        String[] tempcell = line.split("\t\t");
        List<String> cells = new ArrayList<>();
        for (String s : tempcell) {
            cells.add(s);
        }
        cells.remove(0);
        cells.remove(0);
        return cells;
    }

    /**
     * 解析一行txt内容：按双制表符分割，保留所有列（新格式）
     */
    private List<String> parseLineKeepAll(String line) {
        String[] tempcell = line.split("\t\t");
        List<String> cells = new ArrayList<>();
        for (String s : tempcell) {
            cells.add(s);
        }
        return cells;
    }

    /**
     * 创建表头行
     */
    private void createHeaderRow(XSSFSheet sheet, List<String> headerCells) {
        Row headerRow = sheet.createRow(0);
        for (int j = 0; j < headerCells.size(); j++) {
            Cell cell = headerRow.createCell(j);
            cell.setCellValue(headerCells.get(j));
        }
    }

    /**
     * 将工作簿写入输出流
     */
    private ByteArrayOutputStream writeToOutputStream(XSSFWorkbook workbook) throws IOException {
        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        workbook.write(outputStream);
        workbook.close();
        return outputStream;
    }

    // ===================== 图表 =====================

    /**
     * 创建图表
     */
    private void createChart(XSSFSheet sheet, int rowcount, int colcount) {
        XSSFDrawing drawing = sheet.createDrawingPatriarch();

        // 计算图表位置和大小
        int chartTopRow = rowcount + 2;
        int chartWidthCols = Math.min(6 + rowcount / 3, 30);
        int chartHeightRows = Math.min(10 + colcount / 2, 40);
        int chartBottomRow = chartTopRow + chartHeightRows + 6;

        XSSFClientAnchor anchor = drawing.createAnchor(
                0, 0, 0, 0,
                0, chartTopRow,
                chartWidthCols, chartBottomRow
        );

        XSSFChart chart = drawing.createChart(anchor);
        chart.setTitleText("签到人员和签到次数");
        chart.setTitleOverlay(false);

        XDDFChartLegend legend = chart.getOrAddLegend();
        legend.setPosition(LegendPosition.TOP);

        XDDFCategoryAxis bottomAxis = chart.createCategoryAxis(AxisPosition.BOTTOM);
        bottomAxis.setTitle("姓名");

        XDDFValueAxis leftAxis = chart.createValueAxis(AxisPosition.LEFT);
        leftAxis.setTitle("次数");

        XDDFDataSource<String> students = XDDFDataSourcesFactory.fromStringCellRange(
                sheet, new CellRangeAddress(1, rowcount, 1, 1)
        );

        XDDFNumericalDataSource<Double> count = XDDFDataSourcesFactory.fromNumericCellRange(
                sheet, new CellRangeAddress(1, rowcount, colcount, colcount)
        );

        XDDFBarChartData bar = (XDDFBarChartData) chart.createData(
                ChartTypes.BAR, bottomAxis, leftAxis);
        leftAxis.setCrossBetween(AxisCrossBetween.BETWEEN);

        bar.setVaryColors(false);
        XDDFBarChartData.Series series1 = (XDDFBarChartData.Series) bar.addSeries(students, count);
        bar.setBarDirection(BarDirection.COL);
        series1.setTitle("学生签到次数", null);

        XDDFSolidFillProperties fill = new XDDFSolidFillProperties(
                XDDFColor.from(PresetColor.ORANGE_RED));
        series1.setFillProperties(fill);

        chart.plot(bar);
    }

    /**
     * 生成Excel文件名
     */
        public String generateExcelFilename(String txtFilename) {
            if (txtFilename == null) {
                return "output.xlsx";
            }

            String suffix = ".txt";
            String middleName;

            if (txtFilename.endsWith(suffix) && txtFilename.length() > suffix.length()) {
                middleName = txtFilename.substring(0, txtFilename.length() - suffix.length());
            } else {
                int dotIndex = txtFilename.lastIndexOf('.');
                if (dotIndex > 0) {
                    middleName = txtFilename.substring(0, dotIndex);
                } else {
                    middleName = txtFilename;
                }
            }

            return middleName + ".xlsx";
        }

}
