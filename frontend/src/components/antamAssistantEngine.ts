export type AntamIntent="greeting"|"system_help"|"feature_explanation"|"alert_explanation"|"navigation"|"camera"|"family_member"|"settings"|"weather"|"datetime"|"smalltalk"|"out_of_scope";

export function classifyAntamIntent(input:string):AntamIntent{
  const text=input.toLocaleLowerCase("vi");
  if(/xin chào|chào an tâm|bạn là ai|giúp được gì/.test(text))return "greeting";
  if(/thời tiết|nhiệt độ|mưa|nắng/.test(text))return "weather";
  if(/hôm nay.*(thứ|ngày)|mấy giờ|ngày bao nhiêu|giờ rồi/.test(text))return "datetime";
  if(/vì sao.*(cảnh báo|té ngã)|độ tin cậy|91%|mức cao|ai dựa|xác nhận an toàn|cần hỗ trợ/.test(text))return "alert_explanation";
  if(/offline|ngoại tuyến|mất kết nối/.test(text))return "camera";
  if(/làm sao|cách (thêm|bật|xem|thay đổi)|thêm camera|thêm người thân/.test(text))return "system_help";
  if(/mở mục|đi đến|tôi muốn xem|ở đâu/.test(text))return "navigation";
  if(/camera/.test(text))return "camera";
  if(/người thân|người nhận cảnh báo/.test(text))return "family_member";
  if(/cài đặt|thiết lập/.test(text))return "settings";
  if(/ai insight|dashboard|lịch sử sự kiện|cảnh báo khác|chức năng/.test(text))return "feature_explanation";
  if(/chính trị|tôn giáo|chứng khoán|tài chính|pháp luật|lập trình|viết code|toán/.test(text))return "out_of_scope";
  return "out_of_scope";
}

export function answerAntamQuestion(input:string,intent=classifyAntamIntent(input)){
  const text=input.toLocaleLowerCase("vi");
  if(intent==="greeting")return "Xin chào, tôi là An Tâm Assistant. Tôi có thể hướng dẫn sử dụng hệ thống và giải thích cảnh báo AI.";
  if(intent==="weather")return "Tôi chưa được kết nối với dịch vụ thời tiết.";
  if(intent==="datetime")return new Intl.DateTimeFormat("vi-VN",{weekday:"long",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit"}).format(new Date());
  if(intent==="alert_explanation")return "AI tạo cảnh báo khi nhận thấy tư thế thay đổi bất thường và không có chuyển động rõ ràng. Bạn nên xem camera trước khi xác nhận an toàn hoặc chọn Cần hỗ trợ.";
  if(intent==="camera"&&/offline|ngoại tuyến|mất kết nối/.test(text))return "Camera ngoại tuyến khi mất kết nối mạng hoặc nguồn điện. Hãy kiểm tra nguồn, Wi-Fi rồi mở Camera để xem trạng thái.";
  if(intent==="camera"||intent==="navigation")return "Bạn có thể mở mục Camera ở thanh điều hướng để xem camera đang hoạt động và lịch sử sự kiện.";
  if(intent==="family_member")return "Mục Người thân dùng để quản lý thông tin gia đình và người nhận cảnh báo.";
  if(intent==="settings")return "Bạn có thể mở Cài đặt để thay đổi thiết lập camera và cảnh báo.";
  if(intent==="feature_explanation")return "Dashboard tóm tắt trạng thái ngôi nhà; Camera hiển thị hình ảnh; Cảnh báo là tình huống cần kiểm tra; Lịch sử lưu các sự kiện đã ghi nhận.";
  if(intent==="system_help"){
    if(/thêm camera/.test(text))return "Bước 1. Mở Cài đặt.\nBước 2. Chọn Camera.\nBước 3. Nhấn Thêm camera và làm theo hướng dẫn.";
    if(/thêm người thân/.test(text))return "Bước 1. Mở Người thân.\nBước 2. Chọn Thêm người thân.\nBước 3. Nhập thông tin và lưu.";
    return "Hãy mở đúng mục trên thanh điều hướng, sau đó chọn thao tác bạn muốn thực hiện.";
  }
  return "Tôi chỉ hỗ trợ các chức năng của hệ thống An Tâm.";
}
