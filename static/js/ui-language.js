(function () {
  "use strict";

  var translations = {
    en: {
      "Ruang kerja": "Workspace",
      "Keuangan": "Finance",
      "Persediaan": "Inventory",
      "Analisis": "Analysis",
      "Pengelolaan": "Management",
      "Transaksi": "Transactions",
      "Transaksi baru": "New transaction",
      "Catat transaksi": "Record transaction",
      "Riwayat transaksi": "Transaction history",
      "Pindah dana": "Transfers",
      "Saldo awal": "Opening balance",
      "Saldo awal per sumber": "Opening balance by source",
      "Saldo saat ini": "Current balance",
      "Stok harian": "Daily stock",
      "Penyesuaian stok": "Stock adjustment",
      "Pengaturan stok": "Stock settings",
      "Rekap harian": "Daily recap",
      "Rekap mingguan": "Weekly recap",
      "Rekap bulanan": "Monthly recap",
      "Rekap tahunan": "Yearly recap",
      "Item transaksi": "Transaction items",
      "Kategori": "Category",
      "Kunci periode": "Period lock",
      "Profil usaha": "Business profile",
      "Akun": "Account",
      "Tanggal": "Date",
      "Tanggal dibayar": "Payment date",
      "Periode gaji": "Payroll period",
      "Bulan": "Month",
      "Tahun": "Year",
      "Arus": "Flow",
      "Item": "Item",
      "Nominal (Rp)": "Amount (IDR)",
      "Nominal": "Amount",
      "Qty": "Quantity",
      "Satuan": "Unit",
      "Keterangan": "Notes",
      "Kategori": "Category",
      "Metode bayar": "Payment method",
      "Sumber uang": "Money source",
      "Tujuan": "Destination",
      "Semua": "All",
      "Tampilkan": "Show",
      "Reset": "Reset",
      "Cari": "Search",
      "Filter": "Filter",
      "Simpan": "Save",
      "Simpan perubahan": "Save changes",
      "Simpan transaksi": "Save transaction",
      "Batal": "Cancel",
      "Kembali": "Back",
      "Hapus": "Delete",
      "Ubah": "Edit",
      "Tambah": "Add",
      "— Pilih item —": "— Select item —",
      "— Pilih kategori —": "— Select category —",
      "Pilih item": "Select item",
      "Pilih kategori": "Select category",
      "Pilih sumber uang": "Select money source",
      "Tidak ada transaksi": "No transactions",
      "Belum ada transaksi.": "No transactions yet.",
      "Belum ada pindah dana.": "No transfers yet.",
      "Ringkasan": "Summary",
      "Ringkasan Bulan (empat baris)": "Monthly summary (four rows)",
      "Detail per Transaksi": "Transaction details",
      "Detail Transaksi": "Transaction details",
      "Stok per Jenis": "Stock by type",
      "Pemasukan": "Income",
      "Pengeluaran": "Expenses",
      "Mutasi non-operasional": "Non-operating transfers",
      "Selisih": "Net change",
      "Pembukaan": "Opening",
      "Saldo akhir": "Closing balance",
      "Saldo total": "Total balance",
      "Saldo sumber": "Source balance",
      "Stok Berjalan": "Running stock",
      "Nama usaha": "Business name",
      "Alamat": "Address",
      "Telepon": "Phone",
      "Email": "Email",
      "Nama": "Name",
      "Username": "Username",
      "Kata sandi": "Password",
      "Kata sandi lama": "Current password",
      "Kata sandi baru": "New password",
      "Konfirmasi kata sandi baru": "Confirm new password",
      "Status": "Status",
      "Aksi": "Actions",
      "Tanggal mulai usaha": "Business start date",
      "Tanggal saldo awal": "Opening balance date",
      "Bank": "Bank",
      "Tunai": "Cash",
      "Transfer": "Transfer",
      "Export XLSX": "Export XLSX",
      "Ekspor XLSX": "Export XLSX",
      "Terang": "Light",
      "Gelap": "Dark",
      "Pemilik usaha": "Business owner",
      "Keluar": "Log out",
      "Periode terkunci. Buka kunci terlebih dahulu.": "This period is locked. Unlock it first.",
      "Tidak ada data untuk periode ini.": "No data for this period.",
      "Tidak ada gaji untuk periode ini.": "No payroll for this period.",
      "Tidak ada stok": "No stock",
      "Belum ada data": "No data yet",
      "Catat aktivitas hari ini": "Record today's activity",
      "Pengaturan": "Settings",
      "Dashboard": "Dashboard",
      "Wajib diisi": "Required",
      "(opsional)": "(optional)",
      "(wajib": "(required",
      "Pilih tanggal": "Select date",
    },
    ko: {
      "Ruang kerja": "워크스페이스",
      "Keuangan": "재무",
      "Persediaan": "재고",
      "Analisis": "분석",
      "Pengelolaan": "관리",
      "Transaksi": "거래",
      "Transaksi baru": "새 거래",
      "Catat transaksi": "거래 기록",
      "Riwayat transaksi": "거래 내역",
      "Pindah dana": "자금 이체",
      "Saldo awal": "기초 잔액",
      "Saldo awal per sumber": "자금별 기초 잔액",
      "Saldo saat ini": "현재 잔액",
      "Stok harian": "일일 재고",
      "Penyesuaian stok": "재고 조정",
      "Pengaturan stok": "재고 설정",
      "Rekap harian": "일별 요약",
      "Rekap mingguan": "주간 요약",
      "Rekap bulanan": "월간 요약",
      "Rekap tahunan": "연간 요약",
      "Item transaksi": "거래 항목",
      "Kategori": "카테고리",
      "Kunci periode": "기간 잠금",
      "Profil usaha": "사업체 프로필",
      "Akun": "계정",
      "Tanggal": "날짜",
      "Tanggal dibayar": "지급일",
      "Periode gaji": "급여 기간",
      "Bulan": "월",
      "Tahun": "연도",
      "Arus": "유형",
      "Item": "항목",
      "Nominal (Rp)": "금액 (IDR)",
      "Nominal": "금액",
      "Qty": "수량",
      "Satuan": "단위",
      "Keterangan": "메모",
      "Metode bayar": "결제 방법",
      "Sumber uang": "자금 출처",
      "Tujuan": "대상",
      "Semua": "전체",
      "Tampilkan": "표시",
      "Reset": "초기화",
      "Cari": "검색",
      "Filter": "필터",
      "Simpan": "저장",
      "Simpan perubahan": "변경 사항 저장",
      "Simpan transaksi": "거래 저장",
      "Batal": "취소",
      "Kembali": "뒤로",
      "Hapus": "삭제",
      "Ubah": "수정",
      "Tambah": "추가",
      "— Pilih item —": "— 항목 선택 —",
      "— Pilih kategori —": "— 카테고리 선택 —",
      "Pilih item": "항목 선택",
      "Pilih kategori": "카테고리 선택",
      "Pilih sumber uang": "자금 출처 선택",
      "Tidak ada transaksi": "거래 없음",
      "Belum ada transaksi.": "아직 거래가 없습니다.",
      "Belum ada pindah dana.": "아직 이체 내역이 없습니다.",
      "Ringkasan": "요약",
      "Ringkasan Bulan (empat baris)": "월간 요약 (4개 항목)",
      "Detail per Transaksi": "거래별 상세",
      "Detail Transaksi": "거래 상세",
      "Stok per Jenis": "유형별 재고",
      "Pemasukan": "수입",
      "Pengeluaran": "지출",
      "Mutasi non-operasional": "비영업 자금 이동",
      "Selisih": "차액",
      "Pembukaan": "기초",
      "Saldo akhir": "기말 잔액",
      "Saldo total": "총 잔액",
      "Saldo sumber": "출처 잔액",
      "Stok Berjalan": "누적 재고",
      "Nama usaha": "사업체명",
      "Alamat": "주소",
      "Telepon": "전화번호",
      "Email": "이메일",
      "Nama": "이름",
      "Username": "사용자 이름",
      "Kata sandi": "비밀번호",
      "Kata sandi lama": "현재 비밀번호",
      "Kata sandi baru": "새 비밀번호",
      "Konfirmasi kata sandi baru": "새 비밀번호 확인",
      "Status": "상태",
      "Aksi": "작업",
      "Tanggal mulai usaha": "사업 시작일",
      "Tanggal saldo awal": "기초 잔액 날짜",
      "Bank": "은행",
      "Tunai": "현금",
      "Transfer": "이체",
      "Export XLSX": "XLSX 내보내기",
      "Ekspor XLSX": "XLSX 내보내기",
      "Terang": "라이트",
      "Gelap": "다크",
      "Pemilik usaha": "사업주",
      "Keluar": "로그아웃",
      "Periode terkunci. Buka kunci terlebih dahulu.": "잠긴 기간입니다. 먼저 잠금을 해제하세요.",
      "Tidak ada data untuk periode ini.": "이 기간에는 데이터가 없습니다.",
      "Tidak ada gaji untuk periode ini.": "이 기간의 급여가 없습니다.",
      "Tidak ada stok": "재고 없음",
      "Belum ada data": "아직 데이터가 없습니다",
      "Catat aktivitas hari ini": "오늘 활동 기록",
      "Pengaturan": "설정",
      "Dashboard": "대시보드",
      "Wajib diisi": "필수 입력",
      "(opsional)": "(선택 사항)",
      "(wajib": "(필수",
      "Pilih tanggal": "날짜 선택",
    },
  };

  function translateNode(node, language) {
    var original = node.nodeValue;
    var trimmed = original.trim();
    var translated = translations[language] && translations[language][trimmed];
    if (translated) {
      node.nodeValue = original.replace(trimmed, translated);
    }
  }

  function translateTree(root, language) {
    if (!translations[language]) {
      return;
    }
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var parent = node.parentElement;
        if (!parent || /^(SCRIPT|STYLE|TEXTAREA|INPUT|SELECT)$/i.test(parent.tagName)) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) {
      translateNode(walker.currentNode, language);
    }
    if (root.nodeType === Node.ELEMENT_NODE && root.matches("input, select, textarea, button, a")) {
      translateAttributes(root, language);
    }
    root.querySelectorAll("input, select, textarea, button, a").forEach(function (element) {
      translateAttributes(element, language);
    });
  }

  function translateAttributes(element, language) {
    ["aria-label", "placeholder", "title"].forEach(function (attribute) {
      var value = element.getAttribute(attribute);
      var translated = value && translations[language][value.trim()];
      if (translated) {
        element.setAttribute(attribute, value.replace(value.trim(), translated));
      }
    });
  }

  var language = document.documentElement.lang;
  document.addEventListener("DOMContentLoaded", function () {
    translateTree(document.body, language);
  });
  document.body.addEventListener("htmx:afterSwap", function (event) {
    translateTree(event.detail.target, language);
  });
})();
