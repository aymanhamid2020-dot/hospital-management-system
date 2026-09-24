/* واجهة المحاور التشغيلية المتقدمة — تعتمد على API والدوال الموجودة في app.js */
const OP_GROUPS = {
  clinical: [
    ['service-requests','مجموعات الرعاية والوحدات','🧑‍⚕️','service_pending'],
    ['nursing-tasks','خطة التمريض','🩺','nursing_pending'],
    ['surgeries','مسرح العمليات','🏥','surgeries_active'],
    ['admissions','التنويم الداخلي','🛏️','admitted']],
  support: [
    ['blood-bank','بنك الدم','🩸','blood_available'],
    ['maintenance','صيانة الأجهزة','🔧','maintenance_open'],
    ['sterilization','التعقيم','♨️','sterilization_running']],
  governance: [
    ['safety-events','الجودة ومكافحة العدوى والحوادث','🛡️','safety_open'],
    ['budgets','الميزانيات','📊','budget_total'],
    ['assets','الأصول الثابتة','🏗️',null]]
};
const OP_FIELDS = {
  'service-requests':[['patient_id','المريض','number'],['service_type','نوع الخدمة','select',['care_sets','dental','physiotherapy','emergency','home_health','wellness','nutrition']],['title','العنوان'],['details','التفاصيل'],['priority','الأولوية','select',['low','normal','high','critical']]],
  'nursing-tasks':[['patient_id','المريض','number'],['department_id','القسم','number'],['title','المهمة'],['instructions','التعليمات'],['shift','الوردية','select',['day','evening','night']],['priority','الأولوية','select',['low','normal','high','critical']]],
  surgeries:[['patient_id','المريض','number'],['surgeon_id','الجراح','number'],['procedure_name','العملية'],['theater','المسرح'],['priority','الأولوية','select',['emergency','urgent','elective']],'scheduled_at','الموعد','datetime'],
  admissions:[['patient_id','المريض','number'],['bed_id','السرير','number'],['department_id','القسم','number'],['admission_date','وقت الدخول','datetime'],['diagnosis','التشخيص'],['notes','ملاحظات']],
  'blood-bank':[['unit_number','رقم الوحدة'],['donor_name','المتبرع'],['blood_group','فصيلة الدم'],['component','المكون','select',['whole_blood','platelets','plasma','red_cells']],['quantity_ml','الكمية مل','number'],['expiry_date','الصلاحية','datetime']],
  maintenance:[['asset_name','الجهاز'],['serial_number','الرقم التسلسلي'],['location','الموقع'],['issue','العطل'],['priority','الأولوية','select',['low','normal','high','critical']]],
  sterilization:[['machine_name','الجهاز'],['cycle_type','النوع','select',['autoclave','chemical','low_temperature']],['load_description','الحمولة'],['started_at','وقت البدء','datetime'],['operator_name','المشغل']],
  'safety-events':[['category','التصنيف','select',['incident','infection','medication','fall','equipment','other']],['severity','الخطورة','select',['low','medium','high','critical']],['title','الحادث'],['description','الوصف'],['location','الموقع']],
  budgets:[['fiscal_year','السنة','number'],['department','القسم'],['category','البند'],['allocated_amount','المخصص','number'],['spent_amount','المنصرف','number']],
  assets:[['asset_code','رمز الأصل'],['name','الاسم'],['category','الفئة'],['department','القسم'],['purchase_cost','التكلفة','number'],['salvage_value','القيمة المتبقية','number'],['useful_life_years','العمر','number']]
};
const OP_STATUS = {
  'service-requests':['in_progress','completed','cancelled'],'nursing-tasks':['in_progress','completed','cancelled'],
  surgeries:['in_progress','completed','cancelled'],admissions:['discharged','transferred'],
  'blood-bank':['reserved','issued','quarantined','discarded'],maintenance:['in_progress','completed','cancelled'],
  sterilization:['passed','failed'],'safety-events':['investigating','resolved','closed'],assets:['maintenance','retired']
};

let OP_PATH = '';
function opLabel(r) {
  return esc(r.title || r.procedure_name || r.issue || r.load_description || r.unit_number || r.asset_name || r.name || `${r.department || ''} ${r.category || ''}`);
}
function opStatus(path,id,status) {
  api(`/clinical/${path}/status/${id}`,{method:'POST',body:JSON.stringify({status})})
    .then(()=>{toast('تم تحديث الحالة ✅');return navigate(CURRENT_VIEW);})
    .catch(e=>toast(e.message,true));
}
function opField([name,label,type,options]) {
  const control = type==='select'
    ? `<select id="op-${name}">${options.map(x=>`<option>${esc(x)}</option>`).join('')}</select>`
    : `<input id="op-${name}" type="${type||'text'}" ${type==='number'?'step="any"':''} ${type==='datetime'?'required':''}>`;
  return `<div class="field"><label>${label}</label>${control}</div>`;
}
function opSubmit() {
  const data = {};
  (OP_FIELDS[OP_PATH] || []).forEach(([name,,type]) => {
    const value = V('op-'+name);
    if (value !== '' && value != null) data[name] = type==='number' ? Number(value) : value;
  });
  api('/clinical/'+OP_PATH,{method:'POST',body:JSON.stringify(data)})
    .then(()=>{closeModal();toast('تمت الإضافة ✅');return navigate(CURRENT_VIEW);})
    .catch(e=>toast(e.message,true));
}
async function renderOps(main, group) {
  if (!OP_PATH) OP_PATH = OP_GROUPS[group][0][0];
  const ov = await api('/clinical/overview');
  const cards = OP_GROUPS[group].map(([path,title,icon,key]) => `
    <button class="stat" style="cursor:pointer;border:2px solid ${OP_PATH===path?'#2c7be5':'transparent'}" onclick="OP_PATH='${path}';navigate(CURRENT_VIEW)">
      <div class="num">${key ? Number(ov[key] || 0).toLocaleString() : ''}</div><div class="lbl">${icon} ${title}</div>
    </button>`).join('');
  const current = OP_GROUPS[group].find(x => x[0] === OP_PATH) || OP_GROUPS[group][0];
  const rows = await api('/clinical/'+OP_PATH);
  main.innerHTML = `<div class="stats">${cards}</div><div class="card">
    <div class="toolbar"><h3 style="margin:0">${current[2]} ${current[1]}</h3>
      ${isAdmin()||isDoctor()?'<button class="btn success" onclick="opForm()">➕ إضافة</button>':''}
      <input oninput="filterTable('ops-table',this.value)" placeholder="🔍 بحث…"></div>
    <div style="overflow-x:auto"><table id="ops-table"><thead><tr><th>#</th><th>التفاصيل</th><th>الحالة</th><th>التاريخ</th><th>الإجراءات</th></tr></thead>
      <tbody>${rows.map(r=>`<tr><td>${r.id}</td><td>${opLabel(r)}</td><td>${pill(r.status||'سجل')}</td>
      <td>${fmtDate(r.created_at||r.started_at||r.purchase_date||r.admission_date)}</td>
      <td><div class="actions">${(OP_STATUS[OP_PATH]||[]).map(s=>`<button class="btn sm ghost" onclick="opStatus('${OP_PATH}',${r.id},'${s}')">${s}</button>`).join('')}</div></td></tr>`).join('')
      || '<tr><td colspan="5" class="empty">لا توجد سجلات بعد</td></tr>'}</tbody></table></div></div>`;
}
function opForm() {
  openModal('➕ إضافة سجل جديد', `<div class="form-grid">${(OP_FIELDS[OP_PATH]||[]).map(opField).join('')}</div>
    <div class="row2" style="margin-top:12px"><button class="btn success" onclick="opSubmit()">حفظ</button><button class="btn ghost" onclick="closeModal()">إلغاء</button></div>`);
}
Object.assign(VIEWS, {
  clinical: main => renderOps(main, 'clinical'),
  support: main => renderOps(main, 'support'),
  governance: main => renderOps(main, 'governance')
});
Object.assign(TITLES, {clinical:'الرعاية والتشغيل',support:'الدعم والصيانة والتعقيم',governance:'الجودة والموارد'});

